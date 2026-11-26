# Поддержка страницы GitHub

Публичный репозиторий: [xeemoff/tanksession-analytics](https://github.com/xeemoff/tanksession-analytics), основная ветка `main`, лицензия MIT.

- Главная витрина: [README](../README.md), [галерея](SCREENSHOTS_RU.md), [архитектура](ARCHITECTURE_RU.md), [история изменений](../CHANGELOG.md).
- Снимки галереи берутся из браузерного демо; факты работы в игре фиксируются отдельно в [протоколе](CLIENT_VALIDATION_RU.md). Не публикуйте реальные журналы, идентификаторы и личные скриншоты.
- Краткое описание для раздела About находится в [GITHUB_DESCRIPTION_RU.txt](../GITHUB_DESCRIPTION_RU.txt).
- Рекомендуемые темы: `python`, `react`, `typescript`, `gameface`, `game-mod`, `mir-tankov`, `game-analytics`, `dashboard`, `csv`.

## Обновление About владельцем

На главной странице репозитория откройте шестерёнку возле **About**, вставьте актуальный текст описания и обновите темы. Либо выполните из локального клона с установленным и авторизованным GitHub CLI:

```powershell
gh repo edit xeemoff/tanksession-analytics --description (Get-Content -Encoding utf8 -Raw GITHUB_DESCRIPTION_RU.txt).Trim()
gh repo edit xeemoff/tanksession-analytics --add-topic react,typescript,gameface
```

Файл с описанием сам по себе не изменяет метаданные репозитория.

## Версии и публикация

Ранее выпущенная версия v0.3.0 сохраняется как историческая предварительная версия. [Описание выпуска](releases/v0.3.0.md) относится только к этому тегу. Новые кандидаты собираются в GitHub Actions; до подтверждения сценариев не объявляйте их стабильным игровым релизом. См. [правила публикации](PUBLICATION_RU.md).
