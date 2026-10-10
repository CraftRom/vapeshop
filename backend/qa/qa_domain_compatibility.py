"""Domain migration and Telegram-menu behavior without production access."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('domain_config', ROOT / 'deploy/domain_config.py')
domains = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domains)
os.environ.setdefault('BOT_TOKEN', '777001:TESTTOKEN')
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import SetChatMenuButton
from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from shop.telegram_menu import storefront_url, sync_menu


class Migration(unittest.TestCase):
    def test_old_configuration_keeps_www_as_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env';path.write_text('PUBLIC_URL="https://www.elfar.pp.ua/"\n')
            self.assertEqual(domains.load(path), ('elfar.pp.ua', ['www.elfar.pp.ua']))

    def test_arbitrary_aliases_are_validated_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env';path.write_text('PUBLIC_URL=https://shop.test\nMAIN_DOMAIN_ALIASES=old.test,old.test,shop.test\n')
            self.assertEqual(domains.load(path), ('shop.test', ['old.test']))
            for value in ['*.test','old.test;return 200','user@old.test','https://old.test','-bad.test']:
                path.write_text('PUBLIC_URL=https://shop.test\nMAIN_DOMAIN_ALIASES='+value+'\n')
                with self.assertRaises(ValueError): domains.load(path)

    def test_menu_urls_are_canonical(self):
        self.assertEqual(storefront_url('https://www.elfar.pp.ua/'), 'https://elfar.pp.ua/app/')
        self.assertEqual(storefront_url('https://elfar.pp.ua/'), 'https://elfar.pp.ua/app/')
        self.assertEqual(storefront_url(''), '')

    def test_buttons_keep_start_params_and_do_not_rewrite_other_hosts(self):
        from shop.links import canonical_button_url
        old='https://www.elfar.pp.ua/app/?tgWebAppStartParam=product_19#tgWebAppData=launch'
        self.assertEqual(canonical_button_url(old),old.replace('www.elfar.pp.ua','elfar.pp.ua'))
        for link in ['https://www.elfar.pp.ua.evil.test/app/','https://t.me/elfarshop_bot/elfar','https://partner.test/']:
            self.assertEqual(canonical_button_url(link),link)
        from api.schemas import BroadcastIn
        self.assertEqual(BroadcastIn(title='test',text='test',button_url=old).button_url,old.replace('www.elfar.pp.ua','elfar.pp.ua'))

    def certificate(self, staging=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'deploy/nginx').mkdir(parents=True);(p/'bin').mkdir()
            for script in ['domain_config.py','render-nginx.sh','certbot-init.sh']:
                shutil.copy(ROOT/'deploy'/script,p/'deploy'/script)
            shutil.copy(ROOT/'deploy/nginx/app.conf.template',p/'deploy/nginx/app.conf.template')
            (p/'.env').write_text('PUBLIC_URL=https://www.elfar.pp.ua\n')
            docker=p/'bin/docker';docker.write_text('''#!/usr/bin/env python3
import os,sys,json
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
if 'ps' in sys.argv: print('running')
''');docker.chmod(0o700)
            for name,body in [('curl','echo 301'),('sleep','exit 0')]:
                script=p/'bin'/name;script.write_text('#!/bin/sh\n'+body+'\n');script.chmod(0o700)
            result=subprocess.run(['bash',str(p/'deploy/certbot-init.sh'),'www.elfar.pp.ua',*(['--staging'] if staging else [])],capture_output=True,text=True,env={**os.environ,'CERTBOT_EMAIL':'qa@example.test','CALLS':str(p/'calls'),'PATH':str(p/'bin')+':'+os.environ['PATH']},timeout=10)
            calls=[json.loads(v) for v in (p/'calls').read_text().splitlines()]
            return result,calls

    def test_certificate_keeps_both_domains_and_stable_certificate_name(self):
        result,calls=self.certificate()
        self.assertEqual(result.returncode,0,result.stderr)
        issuance=next(v for v in calls if 'certonly' in v)
        self.assertEqual(issuance[issuance.index('--cert-name')+1], 'elfar.pp.ua')
        self.assertEqual([issuance[i+1] for i,v in enumerate(issuance) if v=='-d'],['elfar.pp.ua','www.elfar.pp.ua'])
        self.assertNotIn('--force-renewal',issuance)
        self.assertTrue(any('reload' in v for v in calls))

    def test_staging_cannot_replace_managed_certificate(self):
        result,calls=self.certificate(staging=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('certonly' in v for v in calls))


class TelegramMenu(unittest.IsolatedAsyncioTestCase):
    class Bot:
        def __init__(self): self.menu=None;self.calls=0;self.fail=None
        async def set_chat_menu_button(self,menu_button):
            self.calls+=1
            if self.fail and self.calls==1: raise self.fail
            self.menu=menu_button
        async def get_chat_menu_button(self): return self.menu

    async def test_updates_and_verifies_saved_menu(self):
        bot=self.Bot();bot.menu=MenuButtonWebApp(text='Old',web_app=WebAppInfo(url='https://www.elfar.pp.ua/app/'))
        self.assertTrue(await sync_menu(bot,'https://www.elfar.pp.ua/'))
        self.assertEqual(bot.menu.web_app.url,'https://elfar.pp.ua/app/')

    async def test_transient_failure_retries(self):
        bot=self.Bot();bot.fail=TelegramNetworkError(method=SetChatMenuButton(),message='unavailable')
        with patch('shop.telegram_menu.asyncio.sleep') as sleep:
            self.assertTrue(await sync_menu(bot,'https://elfar.pp.ua'))
            self.assertEqual(bot.calls,2);sleep.assert_awaited_once_with(1)

    async def test_flood_control_waits_requested_interval(self):
        bot=self.Bot();bot.fail=TelegramRetryAfter(method=SetChatMenuButton(),message='rate',retry_after=5)
        with patch('shop.telegram_menu.asyncio.sleep') as sleep:
            self.assertTrue(await sync_menu(bot,'https://elfar.pp.ua'))
            sleep.assert_awaited_once_with(5)

    async def test_wrong_saved_menu_is_not_reported_as_success(self):
        bot=self.Bot()
        async def incorrect():return MenuButtonCommands()
        bot.get_chat_menu_button=incorrect
        with self.assertRaises(RuntimeError): await sync_menu(bot,'https://elfar.pp.ua')

    async def test_previously_scheduled_broadcast_sends_canonical_button(self):
        from shop.telegram import send_broadcast_message
        with patch('shop.telegram._call',return_value=(True,None)) as call:
            await send_broadcast_message(123,'test',button_text='shop',button_url='https://www.elfar.pp.ua/app/?start=old#launch')
            self.assertEqual(call.call_args.args[1]['reply_markup']['inline_keyboard'][0][0]['url'],'https://elfar.pp.ua/app/?start=old#launch')

    async def test_insecure_menu_is_skipped(self):
        bot=self.Bot();self.assertFalse(await sync_menu(bot,'http://localhost'));self.assertEqual(bot.calls,0)


if __name__=='__main__': unittest.main(verbosity=2)
