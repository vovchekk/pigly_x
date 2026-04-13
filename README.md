# Pigly

Новый отдельный проект Pigly под X/Twitter workflow.

## Что уже есть

- Django-проект с отдельным `core`, `users`, `assistant`, `history`
- extension-first лендинг с двуязычным `RU/EN` интерфейсом
- встроенный auth-блок на главной странице
- отдельные страницы входа и регистрации
- custom user, профиль и задел под план/лимиты
- placeholder API для будущих `shorten` и `AI reply`

## Локальный запуск

```powershell
cd C:\Users\kvovc\Desktop\pigly
C:\Users\kvovc\Desktop\diplom\venv\Scripts\python.exe manage.py migrate
C:\Users\kvovc\Desktop\diplom\venv\Scripts\python.exe manage.py runserver
```
