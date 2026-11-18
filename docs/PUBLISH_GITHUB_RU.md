# Публикация TankSession Analytics на GitHub

Репозиторий `xeemoff/tanksession-analytics`, видимость публичная, основная ветка `main`, лицензия MIT. Краткое описание находится в [GITHUB_DESCRIPTION_RU.txt](../GITHUB_DESCRIPTION_RU.txt).

Темы репозитория: `python`, `game-mod`, `mir-tankov`, `game-analytics`, `dashboard`, `csv`.

## Первый выпуск

Команды выполняются из локального репозитория с подготовленным первым коммитом и тегом `v0.3.0`. Проверить их содержимое можно через `git show --stat v0.3.0`. Для публикации нужен вход в GitHub CLI под владельцем репозитория.

```powershell
gh repo create xeemoff/tanksession-analytics --public --source . --remote origin --push --description (Get-Content -Encoding utf8 -Raw GITHUB_DESCRIPTION_RU.txt).Trim()
git push origin refs/tags/v0.3.0
gh repo edit xeemoff/tanksession-analytics --add-topic python,game-mod,mir-tankov,game-analytics,dashboard,csv
gh release create v0.3.0 --repo xeemoff/tanksession-analytics --verify-tag --prerelease --title "TankSession Analytics v0.3.0 — сравнение боёв и техники" --notes-file docs/releases/v0.3.0.md
```

Если репозиторий уже создан, сверьте его владельца и содержимое перед отправкой. [Описание выпуска](releases/v0.3.0.md) фиксирует статус проверки игровой интеграции. GitHub формирует архивы исходников по тегу.
