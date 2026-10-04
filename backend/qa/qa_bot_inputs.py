"""Invalid checkout fields must not advance FSM; summaries must be valid HTML."""
import os, asyncio
from types import SimpleNamespace
from decimal import Decimal
os.environ.update(BOT_TOKEN='777001:QA', JWT_SECRET='t'*32)
from bot.handlers import checkout
from bot.states import Checkout
from qa_common import Report
r=Report('BOT INPUTS')
class State:
    def __init__(self, state, data=None): self.state=state; self.data=data or {}
    async def get_state(self): return self.state
    async def set_state(self, value): self.state=value.state if hasattr(value,'state') else value
    async def update_data(self, **data): self.data.update(data)
    async def get_data(self): return self.data
class Message:
    def __init__(self,text): self.text=text; self.answers=[]
    async def answer(self,text,**kwargs): self.answers.append((text,kwargs))
async def main():
    for fn, state, texts, field in (
        (checkout.step_name,Checkout.name.state,['a','x'*129],'name'),
        (checkout.step_city,Checkout.city.state,['   ','x'*129],'city'),
        (checkout.step_address,Checkout.address.state,['   ','x'*256],'address'),
    ):
        for text in texts:
            context=State(state); message=Message(text)
            await fn(message,context)
            r.check(context.state==state and field not in context.data and bool(message.answers),f'{field}: invalid input stays on the current step ({len(text)} chars)')
    context=State(Checkout.comment.state);message=Message('x'*501)
    await checkout.step_comment(message,context,None,None)
    r.check(context.state==Checkout.comment.state and 'comment' not in context.data,'oversized comment rejected before summary')
    context=State(Checkout.payment.state);answers=[]
    async def answer(*args,**kw): answers.append(args)
    callback=SimpleNamespace(data='pay:unknown',answer=answer)
    await checkout.step_payment(callback,context)
    r.check(context.state==Checkout.payment.state and 'payment' not in context.data and bool(answers),'unknown payment does not advance checkout')
    class Repo:
        async def get_cart(self,uid):
            return [SimpleNamespace(product=SimpleNamespace(name='<Товар & QA>',price=Decimal(10)),qty=1,line_total=Decimal(10)) for _ in range(120)]
    context=State(Checkout.comment.state,{'name':'<Імʼя>','phone':'+380671234567','city':'Київ & область','address':'<Адреса>','comment':'<script>','payment':'cod'})
    message=Message('')
    await checkout._show_summary(message,context,Repo(),SimpleNamespace(id=1,bonus_balance=0))
    text='\n'.join(answer[0] for answer in message.answers)
    r.check('&lt;Товар &amp; QA&gt;' in text and '&lt;Імʼя&gt;' in text and '&lt;script&gt;' in text,'customer and product text is HTML escaped')
    r.check(len(message.answers)>1 and all(len(answer[0])<=3500 for answer in message.answers),'long cart splits into Telegram-sized messages')
    r.check(all(answer[1].get('reply_markup') is None for answer in message.answers[:-1]) and message.answers[-1][1].get('reply_markup') is not None,'confirmation controls appear only after the complete summary')
asyncio.run(main())
raise SystemExit(bool(r.done()))
