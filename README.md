# Swift Translate Win

Windows translator in the style of the Android app "Swift Translate".

## What it does

* **Automatic selection** – select text anywhere (website, browser, any app) and it is grabbed by itself
  (Settings → Select anywhere). It only COPIES (Ctrl+C), never cuts. The pointer must be a text cursor (I-beam),
  so moving windows or files is ignored (can be switched off).
* **After grabbing** (Settings → General): *Translate automatically* ON = the translation box opens by itself;
  OFF = a small bubble appears next to the text, click it to translate.
* **Grab screen text** – hold a key (default **F8**) and the screen freezes with every word found by OCR selectable:
  drag over words, double-click = word, triple-click = line, Ctrl+A = all. Works on images, videos, buttons, PDFs –
  everything you can see. A quick tap keeps the grab screen open until you select or press Esc.
* **Screen snip** (default **F9**) – draw a rectangle, the text inside is recognised, copied and translated.
* **Floating bubble** – dock it to the left, right, top or bottom edge. Drag it onto text and release to translate
  that text. Click for a quick-translate box. Move it: Shift+drag, or press and hold half a second and drag.
  Right-click for the menu.
* **Always on top** – the bubble, trigger bubble and translation box are re-raised every 0.7 s so they stay above
  every window, including other always-on-top apps (each can be switched off in settings).
* **Copy icons** in the original-text and translation fields. 140+ target languages (type to search).
* **API connections** – any OpenAI-compatible endpoint (base URL, model, API key). Tried top to bottom; if one fails
  the next is used, and so on; if all fail one error lists every failure. Test selected / Test all.

## Get the .exe with GitHub Actions

1. Create a repository and upload **all** files, including the hidden `.github/workflows/build.yml`
   (if the folder does not upload: *Add file → Create new file*, name it `.github/workflows/build.yml`, paste the content).
2. Actions tab → **Build Windows EXE** → *Run workflow* (it also runs on every push).
3. Download the artifact **SwiftTranslateWin-exe**. It contains two files:
   * `SwiftTranslateWin.exe` – normal.
   * `SwiftTranslateWin-Admin.exe` – asks for administrator rights; use it if the bubble/selection does not react
     over programs that run as administrator (Task Manager, installers, some tools).

## First start

Tray icon → **Settings → API connections** → Add, pick a preset or fill base URL / model / key, *Test selected*, *Save*.
Choose the target language in *General*.

## Notes

* The input is read by polling the mouse/keyboard state (no global hooks), so Windows cannot silently switch it off.
  The grab key (F8) is not hidden from other programs.
* Windows OCR only reads languages that have an OCR language pack installed (Settings → Select anywhere has a button).
  Copy-based selection works for every language.
* Keyboard-only selections (Shift+Arrows, Ctrl+A) are not detected automatically; use the grab key or snip.
* API keys are stored in plain text in `%APPDATA%\SwiftTranslateWin\config.json`; log: `app.log` in the same folder.
* Windows SmartScreen may warn about an unsigned exe: *More info → Run anyway*.
