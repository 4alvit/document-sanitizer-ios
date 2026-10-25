# App Store text drafts — EN / RU

Text prepared for source [`e40d6933bff2`](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a). **Not submission-ready.** App name reservation is unconfirmed, no live purchase or price is asserted, and no legal/contact details are supplied by this draft. The payment, physical-device and App Store Connect gates remain open in [RELEASE.md](RELEASE.md) and [STOREKIT-TESTING.md](STOREKIT-TESTING.md).

[app-store/localizations.json](app-store/localizations.json) is the machine-readable source for the text below. It is a local authoring format, not an ASC API payload. The review-note translations are two alternatives for each single review-note field; they do not imply that ASC stores localized review notes. All review instructions describe a future validated build, not a successful payment test.

## Unset information and submission gates

- The owner must confirm both localized names, ASC records, final pricing/territories and the rights-holder copyright entry. The one-time, non-consumable product ID in source is `io.github.4alvit.cleansend.pro`; its draft internal reference name is `RedactLeaf Pro`. Its price and ASC registration remain unconfirmed.
- Support URL, privacy URL and App Review contact are intentionally unset. Confirm actual reachable contact information and approve the final public URLs. A GitHub issue tracker alone does not establish the contact information required by Apple's [platform version reference](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/). Do not post private documents or personal contact details in public evidence.
- Complete Developer Program/signing/provisioning and paid agreements, tax/banking and product setup. Resolve native payment findings and validate the actual product on physical-device Sandbox before submission. A controlled fixture, simulator archive or ordinary UI smoke is not payment acceptance.
- Verify physical-device behavior, final privacy declarations, age/content-rights answers and required screenshots, including an IAP review screenshot of the actual offer. Screenshots must use synthetic documents; this text package does not certify screenshot readiness.
- `whatsNew` is unset because Apple does not offer this field for an initial app version. Optional marketing URL is also unset. No fabricated domain, price, address, email, phone number or rights-holder name is used.

## Limits and counting

Apple's [app information reference](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information/) allows 2–30 characters for a name and up to 30 for a subtitle. The [platform version reference](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/) specifies 170 characters for promotional text, 4000 for description, **100 bytes for keywords** and **4000 bytes for app review notes**. The [IAP reference](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information/) specifies 2–30 characters for display name, 45 for description, 64 for reference name, 100 for product ID and 4000 characters for IAP review notes.

The broader [product page guide](https://developer.apple.com/app-store/product-page/) currently differs on IAP limits (35/55) and describes keywords in characters. These drafts use the stricter ASC reference limits (30/45 and 100 bytes). Counts below include line breaks and punctuation in decoded strings, not JSON escaping or Markdown wrappers. All text is NFC and uses BMP characters; codepoint and UTF-16-unit lengths therefore agree here. ASC must still validate the final entries.

## Product facts used

The complete free workflow supports up to 3 pages per workspace. Pro increases the page cap to 30 and enables preset creation; the total workspace cap remains exactly 24,000,000 working pixels, so large pages can hit it sooner. The importer caps each input at 50 MiB. PDF rendering is up to 144 dpi and 2400 pixels on the longest edge; the core also enforces a 6,000,000-pixel page ceiling.

Presets store a user-provided name and normalized rectangles, with limits of 50 presets, 80 characters per name, 200 rectangles per preset and a 1 MiB library. They apply to the selected page after a placement preview and do not align forms automatically. Existing presets remain usable/deletable without Pro; loaded pages remain exportable. See [PRESETS.md](PRESETS.md).

OCR proposes whole recognized lines, with device-supported English/Russian configuration independent of UI language. It cannot promise complete detection. PDF/PNG/JPEG exports are new raster copies; source layers/metadata are not copied, but generated files still contain technical output properties. The temporary workspace clears at restart; presets persist locally. These are implementation facts, not a certification of confidentiality or payment readiness.

Sources: [workspace](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/App/Workspace.swift), [limits](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/Sources/SanitizerCore/Models.swift), [OCR](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/Sources/SanitizerCore/TextRecognizer.swift), [exporter](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/Sources/SanitizerCore/RasterExporter.swift), [preset library](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/App/MaskPresetStore.swift), [Pro and information UI](https://github.com/4alvit/document-sanitizer-ios/blob/e40d6933bff2100c028259aa54be3ea8f3a6a66a/App/ProView.swift).

## English (U.S.) — en-US

**Name:** RedactLeaf: PDF & Photo

**Subtitle:** Hide details. Review. Share.

**Promotional text:** Cover selected details in PDFs and images, check every page, then share new copies. Process documents on your device and reuse area presets with Pro.

**Keywords:** redact,document,mask,receipt,scan,offline,metadata,export,private

### Description

Prepare a copy of a receipt, form or other document before you send it. RedactLeaf lets you hide selected details in PDFs and images, inspect the result and share new copies. Your original files stay unchanged.

CHOOSE WHAT TO HIDE
Draw rectangular areas over details you want to cover, or position them with sliders. Search recognized text across the workspace and choose which matching lines to hide. A confirmed match covers the whole recognized line, not just the search phrase. Recognition supports English and Russian where available on the device; it can miss or misread content.

CHECK BEFORE SHARING
Zoom into the final preview and confirm that you have checked every page before exporting. Selected areas become black pixels. Export one image-only PDF for the batch, or one PNG or JPEG image per page.

FREE AND PRO
The free version includes editing, text search, preview and export for up to 3 pages per workspace. RedactLeaf Pro is an optional one-time in-app purchase, with no subscription. It increases the page limit to 30 and lets you create reusable area presets.

Each workspace also has a total limit of 24,000,000 working pixels. Large pages can reach that limit before the page count, including with Pro. Split larger documents into smaller batches.

REUSE AREA PRESETS
Save up to 50 named presets for documents with similar layouts. A preset stores a name and relative rectangle positions, not a document or recognized text. Preview placement on the selected page before applying it: presets do not align fields automatically. Existing presets remain available to apply or delete if Pro becomes unavailable. Already loaded pages remain viewable and exportable. Restore purchases restores Pro access, not documents or presets.

LOCAL, TEMPORARY WORKSPACE
Document processing takes place on your device, with no required app account or document upload service. The workspace clears when the app restarts, so export before restarting the app. Presets stay on this device and do not sync. Accessing cloud files or Apple's purchase services may require a connection.

KNOW THE LIMITS
Inputs are limited to 50 MiB per file. PDF pages render at up to 144 dpi and 2,400 pixels on the longest edge. Locked PDFs and animated or multi-frame images are not supported.

Copies are rasterized: selectable text, links, forms and accessibility structure are lost, and resolution may decrease. Visible annotations become part of the image; a signature's appearance is not a valid digital signature. Source text layers, attachments and source metadata are not copied, although new files contain technical output properties. OCR is not an automatic privacy check. Inspect every page, including handwriting, faces and other details you did not search for.

### In-app purchase

**Display name:** RedactLeaf Pro

**Description:** Up to 30 pages and reusable area presets

### App review notes — draft

DRAFT for a future validated App Store build. Current payment and physical-device release gates remain open; these steps are not a record of successful payment acceptance.

No app account or demo credentials are required for document editing. Apple handles purchases separately.
1. Launch RedactLeaf and tap "Try a synthetic sample". The built-in receipt is labelled synthetic and contains no real personal data.
2. Draw an area on the receipt, or use "Add area with accessible controls". Optional: use "Find matching lines", then confirm a proposed whole line.
3. Tap "Review clean copies". Inspect the preview and tap "I checked this page" for each page. Export stays disabled until every page is checked. Select PDF, PNG or JPEG, then "Export clean copies" to open the system share sheet. These are new raster copies; originals are unchanged.
4. Return to editing. The top-right menu contains "Saved areas", "Clear workspace" and "Privacy and support".
5. Open the top-left sparkle button ("Unlock Pro" or "Pro") for the paywall and "Restore purchases". The non-consumable product is io.github.4alvit.cleansend.pro. Free supports 3 pages; Pro permits up to 30 and creation of area presets. Both remain limited to 24,000,000 working pixels. Pro is one purchase, not a subscription; the app displays Apple's localized price.
6. With validated Pro access, draw an area, open "Saved areas", then "Save current page areas". Save a generic name. Preview its placement on a selected page before applying. Presets do not align fields automatically.

The workspace is temporary and clears on restart. Presets persist locally without document images or OCR text. Restore purchases does not restore documents or presets. OCR can miss content and does not certify privacy. The release app excludes the development StoreKit configuration. Do not submit until the actual ASC product is available and the payment gates have passed.

### IAP review notes — draft

DRAFT; not ready for submission. RedactLeaf Pro is the non-consumable product io.github.4alvit.cleansend.pro. Open the top-left sparkle button ("Unlock Pro" or "Pro"). The screen contains Apple's localized price and "Restore purchases". No app account is required.

Expected benefit: increase the workspace limit from 3 to 30 pages, subject to the unchanged 24,000,000 working-pixel total, and create reusable area presets. This is not a subscription. With valid Pro access, import a small four-page synthetic PDF; use "Saved areas" > "Save current page areas" on a page with a drawn area to create a preset. Preview placement before applying it. Existing pages remain exportable and saved presets remain usable/deletable if Pro becomes unavailable. Restore purchases restores access, not documents or presets.

Before submission: configure the real ASC product and price; attach a review screenshot of the actual offer; complete purchase, cancellation, pending approval, refund, restore and offline-relaunch acceptance in the intended environment, including physical-device Sandbox checks. Native payment findings remain open. Local StoreKit fixtures and passing controlled tests are not a live product or payment acceptance. Do not submit an unavailable purchase.

### Field counts

| Field | Codepoints | UTF-8 bytes | Enforced limit |
| --- | ---: | ---: | --- |
| name | 23 | 23 | 30 codepoints |
| subtitle | 28 | 28 | 30 codepoints |
| promotionalText | 149 | 149 | 170 codepoints |
| description | 2757 | 2757 | 4000 codepoints |
| keywords | 65 | 65 | 100 utf8Bytes |
| appReviewNotes | 1919 | 1919 | 4000 utf8Bytes |
| inAppPurchase.displayName | 14 | 14 | 30 codepoints |
| inAppPurchase.description | 40 | 40 | 45 codepoints |
| inAppPurchaseReviewNotes | 1265 | 1265 | 4000 codepoints |

## Русский — ru

**Name:** RedactLeaf: PDF и фото

**Subtitle:** Скройте детали перед отправкой

**Promotional text:** Скройте выбранные детали в PDF и изображениях, проверьте страницы и отправьте новые копии. Обработка на устройстве; с Pro можно сохранять шаблоны областей.

**Keywords:** документ,скрыть,чек,маска,копия,офлайн,экспорт

### Description

Подготовьте копию чека, формы или другого документа перед отправкой. RedactLeaf помогает скрыть выбранные детали в PDF и изображениях, проверить результат и отправить новые копии. Исходные файлы остаются без изменений.

ВЫБЕРИТЕ, ЧТО СКРЫТЬ
Нарисуйте прямоугольники поверх нужных деталей или задайте их положение ползунками. Найдите распознанный текст во всей рабочей области и выберите строки, которые хотите закрыть. После подтверждения скрывается вся распознанная строка, а не только поисковая фраза. Распознавание поддерживает русский и английский, если они доступны на устройстве, но может пропустить или неверно прочитать текст.

ПРОВЕРЬТЕ ПЕРЕД ОТПРАВКОЙ
Увеличьте итоговый предпросмотр и отметьте каждую страницу как проверенную перед экспортом. Выбранные области заменяются чёрными пикселями. Сохраните пакет как один PDF из изображений либо как отдельные PNG или JPEG для каждой страницы.

БЕСПЛАТНАЯ ВЕРСИЯ И PRO
Бесплатная версия включает редактирование, поиск текста, предпросмотр и экспорт до 3 страниц в одной рабочей области. RedactLeaf Pro — дополнительная разовая покупка внутри приложения, без подписки. Она увеличивает предел до 30 страниц и позволяет создавать шаблоны областей.

В каждой рабочей области действует общий предел в 24 000 000 рабочих пикселей. Крупные страницы могут исчерпать его раньше лимита страниц, в том числе с Pro. Большие документы потребуется разделить на меньшие пакеты.

ПОВТОРНО ИСПОЛЬЗУЙТЕ ОБЛАСТИ
Сохраните до 50 именованных шаблонов для документов с похожим расположением полей. Шаблон хранит название и относительные координаты прямоугольников, без документа и распознанного текста. Перед применением проверьте положение на выбранной странице: автоматического выравнивания полей нет. Если Pro недоступен, готовые шаблоны по-прежнему можно применять и удалять, а уже загруженные страницы — просматривать и экспортировать. Восстановление покупок возвращает доступ к Pro, но не документы или шаблоны.

ЛОКАЛЬНАЯ ВРЕМЕННАЯ РАБОЧАЯ ОБЛАСТЬ
Документы обрабатываются на вашем устройстве, без обязательной учётной записи приложения и сервиса загрузки документов. При перезапуске рабочая область очищается: экспортируйте результат до перезапуска. Шаблоны остаются на этом устройстве и не синхронизируются. Для доступа к облачным файлам и сервисам покупок Apple может потребоваться интернет.

УЧИТЫВАЙТЕ ОГРАНИЧЕНИЯ
Размер исходного файла — до 50 МиБ. Страницы PDF преобразуются с разрешением до 144 dpi и до 2400 пикселей по длинной стороне. Заблокированные PDF, анимированные и многокадровые изображения не поддерживаются.

Копии растровые: выделяемый текст, ссылки, формы и структура доступности теряются; разрешение может уменьшиться. Видимые аннотации становятся частью изображения; изображение подписи не является действительной цифровой подписью. Исходные текстовые слои, вложения и метаданные не копируются, но новые файлы содержат технические свойства результата. OCR не заменяет проверку конфиденциальности. Осмотрите каждую страницу, включая рукописный текст, лица и детали, которые вы не искали.

### In-app purchase

**Display name:** RedactLeaf Pro

**Description:** До 30 страниц и шаблоны областей

### App review notes — draft

ЧЕРНОВИК для будущей проверенной сборки App Store. Проверки платежей и физических устройств не завершены; эти шаги не подтверждают приёмку покупок.

Для работы с документами учётная запись приложения не нужна. Покупки отдельно обрабатывает Apple.
1. Откройте RedactLeaf и нажмите «Открыть учебный пример». Чек помечен как учебный и не содержит реальных личных данных.
2. Нарисуйте область на чеке или нажмите «Добавить область с помощью ползунков». Для поиска используйте «Найти строки с совпадениями» и подтвердите нужную строку целиком.
3. Нажмите «Проверить готовые копии». Осмотрите результат и отметьте «Я проверил эту страницу» на каждой странице. До этого экспорт недоступен. Выберите PDF, PNG или JPEG и нажмите «Экспортировать готовые копии»: откроется системное меню отправки. Копии растровые, оригиналы не меняются.
4. Меню справа вверху содержит «Шаблоны областей», «Очистить рабочую область» и «Конфиденциальность и поддержка».
5. Кнопка со звёздочками слева вверху («Открыть Pro» или «Pro») открывает покупку и «Восстановить покупки». Продукт io.github.4alvit.cleansend.pro — разовая покупка без подписки. Бесплатно доступны 3 страницы; Pro даёт до 30 и создание шаблонов. Общий предел — 24 000 000 рабочих пикселей. Цену предоставляет Apple.
6. При подтверждённом доступе Pro нарисуйте область, откройте «Шаблоны областей» и «Сохранить области этой страницы». Сохраните общее название и проверьте размещение перед применением к выбранной странице. Автовыравнивания полей нет.

Перезапуск очищает рабочую область. Шаблоны хранятся локально без изображений и распознанного текста. Восстановление покупок не возвращает документы и шаблоны. OCR может пропустить данные. Сборка Release не содержит тестовой конфигурации StoreKit. Отправка на проверку возможна только после настройки реального продукта ASC и прохождения платёжных проверок.

### IAP review notes — draft

ЧЕРНОВИК; к отправке не готов. RedactLeaf Pro — разовая покупка (non-consumable) io.github.4alvit.cleansend.pro. Откройте кнопку со звёздочками слева вверху («Открыть Pro» или «Pro»). На экране находятся цена Apple и «Восстановить покупки». Учётная запись приложения не нужна.

Ожидаемые возможности: до 30 страниц вместо 3 при прежнем общем пределе в 24 000 000 рабочих пикселей и создание шаблонов областей. Подписки нет. При действующем доступе Pro импортируйте небольшой учебный PDF из четырёх страниц. Нарисуйте область и выберите «Шаблоны областей» > «Сохранить области этой страницы». Проверьте размещение шаблона перед применением. Если Pro недоступен, загруженные страницы можно экспортировать, а сохранённые шаблоны — применять и удалять. Восстановление покупок возвращает доступ, но не документы и шаблоны.

Перед отправкой: настройте реальный продукт и цену в ASC, приложите снимок действующего предложения, завершите проверки покупки, отмены, ожидания одобрения, возврата средств, восстановления и запуска без сети, включая Sandbox на физическом устройстве. Замечания по нативным платежам остаются открытыми. Локальная конфигурация StoreKit и контролируемые тесты не подтверждают готовность платежей. Не отправляйте недоступную покупку.

### Field counts

| Field | Codepoints | UTF-8 bytes | Enforced limit |
| --- | ---: | ---: | --- |
| name | 22 | 27 | 30 codepoints |
| subtitle | 30 | 57 | 30 codepoints |
| promotionalText | 155 | 279 | 170 codepoints |
| description | 3050 | 5551 | 4000 codepoints |
| keywords | 46 | 86 | 100 utf8Bytes |
| appReviewNotes | 1849 | 3293 | 4000 utf8Bytes |
| inAppPurchase.displayName | 14 | 14 | 30 codepoints |
| inAppPurchase.description | 32 | 57 | 45 codepoints |
| inAppPurchaseReviewNotes | 1249 | 2200 | 4000 codepoints |

Shared IAP reference name: 14 codepoints / 14 UTF-8 bytes (limit 64 characters). Product ID: 30 codepoints / 30 UTF-8 bytes (limit 100 characters). No text here has been uploaded to App Store Connect.
