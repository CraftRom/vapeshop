# Точка входу Vercel

`index.py` — ASGI-обгортка навколо `backend/api/main.py`.

Вміст цієї теки Vercel перетворює на serverless-функції. Код бекенду лежить
у `backend/` і додається до функції через `includeFiles` у `vercel.json`.

Для власного сервера ця тека не потрібна — там API запускається як
довгоживучий процес через uvicorn.
