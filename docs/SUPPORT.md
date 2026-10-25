# RedactLeaf support — prerelease

[English](#english) · [Русский](#русский)

## English

Updated 24 October 2026. These instructions describe the prerelease at [source revision e40d693](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a). App Store purchase availability is not established by this page.

### Contact

Use the [RedactLeaf GitHub issue tracker](https://github.com/4alvit/document-sanitizer-ios/issues) for non-sensitive bug reports, questions and feature requests. It is readable without signing in. A GitHub account and sign-in are required to submit an issue.

**Issues, usernames and attachments are public.** This is not a confidential support channel. Do not upload personal documents, photos of real private information, receipts, transaction identifiers, Apple Account details, passwords or full device logs. If an example is needed, create a small synthetic file with invented content. Review screenshots for private filenames and notification content before posting. You can report a problem without attaching a file.

Include only what is needed to reproduce the issue: the app version/build, iOS version, device model, app language, import route (Files or Share Extension), file type and approximate size/page count, steps taken, expected result and the visible error message with any private text removed. No response-time commitment is offered for this prerelease.

### Import and queued files

Choose **Import PDF or images** to select files through Files. If a provider cannot supply a file, first make it available locally in Files and try again. Password-protected PDFs must be unlocked with their password in a suitable app before import. Try a smaller batch if the app reports a size or page limit: each input file has a 50 MiB limit (52,428,800 bytes, shown as 50 MB in the app). A free workspace accepts up to 3 pages, and Pro supports up to 30. Both have the same limit of 24 million working pixels across the workspace.

The Share Extension queues copies; it does not hide content. After queuing, open RedactLeaf and choose **Import this batch**. Import one batch at a time. The extension accepts 1–20 PDF/image attachments, up to 50 MiB total (52,428,800 bytes), with a limit of 5 ready batches queued. If the shared container is unavailable, import through Files inside RedactLeaf.

### Check the result before sharing

Text search suggests whole recognized lines. Nothing is hidden until you confirm a suggestion or add an area manually. OCR can miss text and does not find every face, signature or other private detail. Choose **Review clean copies**, zoom in and check every page before **Export clean copies**.

Output is one image-only PDF per batch, or one JPEG/PNG image per page. Selectable text, links, forms and accessibility structure are lost, and resolution may be reduced. Original files stay unchanged. A receiving app or recipient controls the copy you share with it.

### Remove local data

- **Clear workspace** removes current pages and edits. Export anything you need first; there is no saved project to reopen after an app restart. This command does not clear queued files or saved presets.
- In **Shared files**, use **Discard** for a batch or **Clear all queued files** for the displayed queue. If files are in use, let the operation finish and retry. Expiry after 24 hours is checked by the main app, not by a background deletion timer.
- In **Saved areas**, delete individual presets or use **Delete all presets**. Resetting the library cannot be undone. Presets are excluded from backups and do not sync. Deleting a preset does not remove areas already applied to an open page.

The app attempts to clean up temporary exports after the share sheet closes or at the next app start. Copies already saved in Files or sent to another app must be managed there. More detail is in the [privacy policy](PRIVACY.md).

### Pro and restore

In a build where App Store purchases are available, open **Unlock Pro** or **Pro** and choose **Restore purchases** while signed in to the Apple Account used for the purchase. If the price cannot load, check connectivity and use **Reload App Store price**. Loaded workspace content remains viewable and exportable if Pro is unavailable. Creating new presets and adding pages beyond the free allowance require Pro.

Apple provides [help with restoring in-app purchases](https://support.apple.com/en-us/108096) and [refund requests for purchases made through Apple](https://support.apple.com/en-us/118223). Refund eligibility is determined by Apple; do not post billing evidence in public GitHub issues. This prerelease page does not certify a completed production purchase or restore flow.

## Русский

Обновлено 24 октября 2026 года. Инструкции описывают предварительную версию по [исходному коду e40d693](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a). Эта страница не подтверждает доступность покупок приложения в App Store.

### Связь с поддержкой

Для несекретных сообщений об ошибках, вопросов и предложений используйте [GitHub Issues RedactLeaf](https://github.com/4alvit/document-sanitizer-ios/issues). Читать обращения можно без входа. Для отправки обращения нужен аккаунт GitHub и вход в него.

**Обращения, имена пользователей и вложения общедоступны.** Это не конфиденциальный канал поддержки. Не загружайте личные документы, фотографии с реальными закрытыми данными, чеки, идентификаторы транзакций, данные Аккаунта Apple, пароли или полные журналы устройства. Если нужен пример, создайте небольшой файл с вымышленным содержимым. Перед публикацией снимка экрана проверьте имена файлов и уведомления. Сообщить о проблеме можно без вложения.

Укажите только сведения для воспроизведения ошибки: версию и сборку приложения, версию iOS, модель устройства, язык приложения, способ импорта («Файлы» или расширение меню «Поделиться»), тип файла, примерный размер и число страниц, ваши действия, ожидаемый результат и видимый текст ошибки без личных данных. Для предварительной версии срок ответа не гарантируется.

### Импорт и очередь файлов

Нажмите **«Импорт PDF или изображений»**, чтобы выбрать документы через «Файлы». Если провайдер не может предоставить файл, сначала сделайте его доступным локально в «Файлах» и повторите импорт. PDF с паролем нужно предварительно разблокировать с помощью этого пароля в подходящем приложении. При сообщении о лимите размера или страниц попробуйте меньший пакет: предел для одного исходного файла — 50 МиБ (52 428 800 байт, в приложении обозначено как 50 МБ). Бесплатная рабочая область принимает до 3 страниц, Pro — до 30. В обоих случаях действует общий предел — 24 миллиона рабочих пикселей на всю рабочую область.

Расширение меню «Поделиться» добавляет копии в очередь, но не скрывает содержимое. После добавления откройте RedactLeaf и нажмите **«Импортировать пакет»**. Импортируйте по одному пакету. Расширение принимает от 1 до 20 PDF/изображений общим размером до 50 МиБ (52 428 800 байт); лимит очереди — 5 готовых пакетов. Если общий контейнер недоступен, импортируйте через «Файлы» внутри RedactLeaf.

### Проверка перед отправкой

Поиск предлагает целые распознанные строки. Ничего не скрывается, пока вы не подтвердите предложение или не добавите область вручную. OCR может пропускать текст и не находит все лица, подписи и другие личные детали. Нажмите **«Проверить готовые копии»**, увеличьте изображение и проверьте каждую страницу перед командой **«Экспортировать готовые копии»**.

Результат — один PDF из изображений на весь пакет либо отдельное JPEG/PNG-изображение каждой страницы. Выделяемый текст, ссылки, формы и структура доступности теряются; разрешение может уменьшиться. Оригиналы не изменяются. Копией, отправленной в другое приложение или адресату, управляет получатель.

### Удаление локальных данных

- **«Очистить рабочую область»** удаляет текущие страницы и правки. Сначала экспортируйте нужный результат: сохранённого проекта, который можно открыть после перезапуска приложения, нет. Команда не очищает очередь и шаблоны.
- В разделе очереди нажмите **«Удалить из очереди»** для отдельного пакета или **«Очистить всю очередь»** для отображаемых пакетов. Если файлы используются, дождитесь завершения операции и повторите попытку. Срок 24 часа проверяется основным приложением; фонового таймера удаления нет.
- В разделе **«Шаблоны областей»** удаляйте отдельные шаблоны или выберите **«Удалить все шаблоны»**. Сброс библиотеки нельзя отменить. Шаблоны исключены из резервного копирования и не синхронизируются. Удаление шаблона не убирает области, уже применённые к открытой странице.

Приложение пытается очистить временные файлы экспорта после закрытия меню «Поделиться» или при следующем запуске. Копии, уже сохранённые в «Файлах» или переданные другому приложению, нужно удалять там. Подробности — в [политике конфиденциальности](PRIVACY.md).

### Pro и восстановление покупок

В сборке с доступными покупками App Store откройте экран Pro и выберите **«Восстановить покупки»**, войдя в Аккаунт Apple, с которого была сделана покупка. Если цена не загружается, проверьте подключение и нажмите **«Загрузить цену ещё раз»**. Загруженные страницы остаются доступными для просмотра и экспорта, даже если Pro недоступен. Создание новых шаблонов и добавление страниц сверх бесплатного лимита требуют Pro.

У Apple есть инструкции по [восстановлению встроенных покупок](https://support.apple.com/en-us/108096) и [запросу возврата за покупки у Apple](https://support.apple.com/en-us/118223). Возможность возврата определяет Apple; не публикуйте платёжные документы в GitHub Issues. Эта страница предварительной версии не подтверждает успешную проверку реальной покупки или восстановления через App Store.
