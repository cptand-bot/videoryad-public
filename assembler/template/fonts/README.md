# Шрифты текстовых всплывашек

Лежат ЗДЕСЬ, а не в системе, чтобы облако рисовало ровно тем же файлом, что и
дашборд: раннер GitHub несёт свой случайный набор шрифтов, и выбор
пользователя молча превращался бы в DejaVu (2026-10-17).

| кнопка на дашборде | файл | что это |
|---|---|---|
| ОБЫЧНЫЙ | системный DejaVuSans-Bold | дефолт, как было до 17.10 |
| ARIAL | `Arimo-Bold.ttf` | метрический клон Arial (Google, OFL) |
| TIMES | `Tinos-Bold.ttf` | метрический клон Times New Roman (OFL) |
| OSWALD | `Oswald-Bold.ttf` | узкий новостной |
| MONTSERRAT | `Montserrat-Bold.ttf` | круглый современный |
| ROBOTO | `RobotoCondensed-Bold.ttf` | узкий современный |

Все пять — свободные лицензии (OFL/Apache), кириллица проверена. Arimo,
Oswald, Montserrat и RobotoCondensed — переменные (variable) файлы: жирное
начертание выставляется `set_variation_by_name("Bold")`, и если FreeType этого
не умеет, текст рисуется обычным весом, но ТЕМ ЖЕ шрифтом.
