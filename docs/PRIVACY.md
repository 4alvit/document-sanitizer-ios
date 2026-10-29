# RedactLeaf privacy policy — prerelease

[English](#english) · [Русский](#русский)

## English

Updated 24 October 2026. This page describes the prerelease app and Share Extension at [source revision e40d693](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a). It does not announce App Store availability.

### Documents and text recognition

RedactLeaf processes the PDF and image files you select on your device. It does not upload documents, search terms or saved areas to a developer-operated server. It has no required RedactLeaf account, advertising, analytics service, third-party crash-reporting SDK or app-provided cloud sync.

The app reads selected files to make working copies and leaves the originals unchanged. Working page images, source names, selected areas, search terms and recognized text are used locally. Text recognition uses Apple's Vision framework on the device. Search suggestions can miss private information; you decide which areas to hide and review the result before export.

### Local storage and deletion

- **Workspace:** working pages, edits and text-search results are held in memory, not saved as a document project. **Clear workspace** removes the current pages, edits and search query. Restarting the app starts a new workspace. Returning from the background does not itself clear it.
- **Temporary files:** the app makes local import copies and attempts to remove them when import finishes or is cancelled. It attempts to remove temporary exports when the system share sheet finishes or disappears, and leftover workspace files when a new workspace starts after a restart. An unfinished operation or a file-system error can delay cleanup.
- **Share Extension queue:** sending files to RedactLeaf from another app stores copies in a local container shared with the main app. Copies can still contain the original private content and filenames: queuing is not redaction. The app attempts to remove a batch after successful import or when you discard it; failed or cancelled imports retain it. Copies older than 24 hours are eligible for deletion when the main app next checks the queue. An active import is protected until its worker finishes. There is no guaranteed background deletion at the 24-hour mark. **Discard** and **Clear all queued files** manage the queue separately from the workspace.
- **Saved areas:** presets persist across app restarts. Each contains a generated identifier, the name you enter and relative rectangle positions. They contain no document images, thumbnails, recognized text, source filenames or file URLs. Use a generic name without private details. Delete individual presets or choose **Delete all presets** in **Saved areas**. Clearing the workspace does not remove presets; deleting a preset does not remove areas already applied to an open page.

The app sets iOS Complete file protection on import copies, exports, queued copies and preset files, and excludes the queue and preset library from backups. These are operating-system storage protections, not a promise of forensic erasure or protection against every form of device access.

### Exporting and other services

Export creates new image-only copies with neutral filenames. It does not copy the original document's hidden text layers, interactive objects, attachments or source metadata. New files can contain technical format information, such as image dimensions or the PDF creator name. Any private detail left visible on a page remains visible in the export.

You choose where to send or save an export through the system share sheet. The receiving app, storage provider or recipient controls its own copies and privacy practices. RedactLeaf cannot recall or delete those copies. A provider you select in Files may also use its own cloud service; RedactLeaf does not control that provider.

### Purchases

Pro purchase and restore requests use Apple's StoreKit and App Store services. The app reads product and transaction information, including identifiers, verification status, dates and revocation status, to determine Pro access. It does not receive your payment-card details or send transaction records to a developer-operated server. Apple's handling of App Store information is described in [App Store & Privacy](https://www.apple.com/legal/privacy/data/en/app-store/).

### Support and privacy questions

See the separate [support page](SUPPORT.md). The current contact route is the [public GitHub issue tracker](https://github.com/4alvit/document-sanitizer-ios/issues). Reading it does not require an account; submitting an issue requires a GitHub account. Your username, issue text and attachments are public and available to the maintainers and other readers. Use it only for non-sensitive questions and synthetic examples. Do not post personal documents, payment records, passwords or other private information. GitHub handles website and account data under its [privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

The developer has no server copy of your imported documents or presets to retrieve or delete. Use the local controls above for those files. Deleting local app data does not delete a public support issue or copies held by other services.

## Русский

Обновлено 24 октября 2026 года. Эта страница описывает предварительную версию приложения и расширения меню «Поделиться» по [исходному коду e40d693](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a). Она не означает, что приложение уже доступно в App Store.

### Документы и распознавание текста

RedactLeaf обрабатывает выбранные вами PDF и изображения на вашем устройстве. Приложение не загружает документы, поисковые запросы или сохранённые области на сервер разработчика. Для RedactLeaf не нужен отдельный аккаунт. В приложении нет рекламы, сервиса аналитики, стороннего SDK отправки отчётов о сбоях или собственной облачной синхронизации.

Приложение читает выбранные файлы, создаёт рабочие копии и не изменяет оригиналы. Изображения страниц, исходные имена файлов, выбранные области, поисковые запросы и распознанный текст используются локально. Текст распознаётся на устройстве средствами Apple Vision. Поиск может пропустить личную информацию: вы сами выбираете области для скрытия и проверяете результат перед экспортом.

### Локальное хранение и удаление

- **Рабочая область:** страницы, правки и результаты поиска находятся в памяти и не сохраняются как проект документа. Команда **«Очистить рабочую область»** удаляет текущие страницы, правки и поисковый запрос. После перезапуска создаётся новая рабочая область. Само возвращение из фона её не очищает.
- **Временные файлы:** приложение создаёт локальные копии для импорта и пытается удалить их после завершения или отмены импорта. Оно пытается удалить временные файлы экспорта после завершения работы или закрытия системного меню «Поделиться», а оставшиеся временные файлы — при создании новой рабочей области после перезапуска. Незавершённая операция или ошибка файловой системы может задержать очистку.
- **Очередь расширения:** при передаче файлов в RedactLeaf из другого приложения копии сохраняются в локальном контейнере, общем для расширения и основного приложения. В них ещё могут находиться исходные личные данные и имена файлов: добавление в очередь не скрывает информацию. После успешного импорта или по вашей команде приложение пытается удалить пакет; при ошибке или отмене импорта он остаётся в очереди. Копии старше 24 часов подлежат удалению при следующей проверке очереди основным приложением. Файлы активного импорта сохраняются до завершения его обработки. Фоновое удаление ровно через 24 часа не гарантируется. Команды **«Удалить из очереди»** и **«Очистить всю очередь»** управляют очередью отдельно от рабочей области.
- **Шаблоны областей:** сохраняются между запусками. Каждый содержит созданный приложением идентификатор, введённое вами имя и относительные координаты прямоугольников. В них нет изображений документов, миниатюр, распознанного текста, исходных имён файлов или файловых URL. Выбирайте нейтральные имена без личных данных. Удаляйте отдельные шаблоны или выберите **«Удалить все шаблоны»** в разделе **«Шаблоны областей»**. Очистка рабочей области не удаляет шаблоны; удаление шаблона не убирает области, уже применённые к открытой странице.

Для копий импорта, файлов экспорта, очереди и файлов шаблонов приложение устанавливает защиту файлов iOS Complete file protection. Очередь и библиотека шаблонов исключены из резервного копирования. Это средства защиты хранения операционной системы, а не гарантия безвозвратного стирания или защиты от любого доступа к устройству.

### Экспорт и другие сервисы

Экспорт создаёт новые копии из изображений с нейтральными именами файлов. Исходные скрытые текстовые слои, интерактивные объекты, вложения и метаданные документа не копируются. Новые файлы могут содержать технические сведения формата, например размеры изображения или имя создателя PDF. Личная информация, оставшаяся видимой на странице, останется видимой и в экспортированном файле.

Вы сами выбираете получателя или место сохранения в системном меню «Поделиться». Приложение-получатель, сервис хранения или адресат управляет своими копиями и правилами конфиденциальности. RedactLeaf не может отозвать или удалить эти копии. Провайдер, выбранный в приложении «Файлы», также может использовать собственное облачное хранилище; RedactLeaf им не управляет.

### Покупки

Покупка Pro и восстановление покупок используют Apple StoreKit и App Store. Для определения доступа к Pro приложение читает сведения о продукте и транзакциях: идентификаторы, статус проверки, даты и статус отзыва покупки. Приложение не получает реквизиты вашей платёжной карты и не отправляет записи о транзакциях на сервер разработчика. Обработка информации App Store компанией Apple описана на странице [App Store и конфиденциальность](https://www.apple.com/legal/privacy/data/en/app-store/).

### Поддержка и вопросы о конфиденциальности

См. отдельную [страницу поддержки](SUPPORT.md). Текущий способ связи — [публичный раздел GitHub Issues](https://github.com/4alvit/document-sanitizer-ios/issues). Для чтения аккаунт не нужен; для отправки обращения нужен аккаунт GitHub. Ваше имя пользователя, текст и вложения будут общедоступны разработчикам и другим читателям. Используйте этот канал только для несекретных вопросов и примеров с вымышленными данными. Не публикуйте личные документы, платёжные сведения, пароли и другую закрытую информацию. GitHub обрабатывает данные сайта и аккаунта по своей [политике конфиденциальности](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

У разработчика нет серверной копии импортированных вами документов или шаблонов, которую можно было бы получить или удалить. Для этих данных используйте описанные выше локальные команды. Удаление данных приложения не удаляет публичное обращение в поддержку или копии в других сервисах.
