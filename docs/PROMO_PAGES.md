# Конструктор промо-сторінок

Модуль **Промо-сторінки** створює легкі landing pages за одним контрольованим шаблоном. Панель не приймає CSS, JavaScript або довільний HTML: редагуються лише текстові поля, промокод, CTA, локальні зображення, домен і SEO-дані.

## Модель публікації

- `draft_config` — поточна чернетка редактора.
- `published_config` — snapshot останньої успішної публікації.
- «Зберегти» не змінює живий сайт.
- «Опублікувати» копіює чернетку в production snapshot і збільшує version.
- «Зняти» вимикає публічну сторінку без видалення налаштувань і статистики.

Це дозволяє постійно редагувати та повторно публікувати сторінку без рестарту API/nginx після первинного підключення домену.

## Зображення

Промо-сторінки приймають тільки `/media/...`. Файли завантажуються через наявне локальне сховище панелі та віддаються nginx напряму. Зовнішні hotlink-зображення відхиляються API.

## SEO

Шаблон автоматично формує:

- semantic HTML5 і коректний `lang`;
- `<title>`, description, robots, canonical;
- Open Graph і Twitter Card;
- JSON-LD `WebPage`;
- абсолютні URL social images;
- responsive viewport;
- один H1;
- мінімальну сторінку без WordPress/WPBakery/runtime JS.

Редактор має окремі поля для SEO title/description, canonical, robots, OG title/description/image/locale/site name та schema name/description.

## Статистика

Зберігаються денні агрегати `views` і `clicks`; CTR обчислюється як `clicks / views`. IP, cookie та окремі event rows не зберігаються. Відомі crawler/bot User-Agent не збільшують views.

CTA на production веде через `/go`: API збільшує click counter та робить 302 redirect на налаштований URL.

## Новий домен

1. Додайте DNS A/AAAA запис на сервер.
2. На сервері в `deploy/` виконайте:

   `./promo-domain-add.sh promo.example.com admin@example.com`

3. У панелі створіть промо-сторінку з **точно таким самим** доменом.
4. Натисніть «Опублікувати».

Скрипт одноразово отримує TLS-сертифікат, створює ізольований nginx server block і reload-ить nginx. Панель навмисно не отримує Docker socket/root-доступ.

Для відключення nginx route:

`./promo-domain-remove.sh promo.example.com`

Сертифікат автоматично не стирається, щоб видалення route не стало необоротною операцією.
