# Swift Translate Win

Windows translator in the style of the Android app "Swift Translate":

* **Floating bubble** on the left or right screen edge. **Drag it onto any text and release** – the text under
  the pointer is read and translated. Click it for a quick-translate box. Right-click for the menu.
  Shift+drag moves the bubble (it snaps to the nearest edge).
* **Select text anywhere** (Settings → Select anywhere): hold a key you choose (default **F8**) and
  double-click a word or drag-select text in *any* program. The text is **copied** (Ctrl+C, never cut),
  a small bubble appears next to it, click it to see the translation.
  If the program has nothing to copy (images, some custom UIs) the text is read from the screen with Windows OCR.
* **Screen snip** (default **F9**): draw a rectangle on screen, the text inside is recognised, copied and translated.
* **API connections**: any OpenAI-compatible endpoint (base URL, model, API key). Add as many as you like.
  They are tried top to bottom; if one fails the next is used and so on. If all fail you get one error that lists
  every failure. "Test selected" / "Test all" check the connections.

## Get the .exe with GitHub Actions

1. Create a new GitHub repository.
2. Upload **all** files of this folder, keeping the structure – including the hidden `.github/workflows/build.yml`
   (easiest: unzip, then drag the *contents* of the folder into the GitHub upload page, or use GitHub Desktop / git).
3. Open the **Actions** tab → **Build Windows EXE** → it runs automatically on push (or press *Run workflow*).
4. When it is green, open the run and download the artifact **SwiftTranslateWin-exe**. Unzip, run `SwiftTranslateWin.exe`.
   (Pushing a tag like `v1.0` also attaches the exe to a GitHub Release.)

## First start

1. Tray icon (near the clock) → **Settings → API connections** → *Add*, pick a preset or fill base URL, model and key,
   press **Test selected**, then **Save**.
2. Pick the target language in *General*.

## Notes and limits

* Windows may show SmartScreen for an unsigned exe: *More info → Run anyway*.
* Programs running **as administrator** ignore simulated Ctrl+C / clicks from a normal program. Run the app as
  administrator if you need to select text inside such programs.
* The held key is hidden from other programs (F8 does nothing there) unless you disable that in settings. Modifier keys
  (Ctrl/Shift/Alt) can be used as the trigger but they are never hidden and Alt/Ctrl combine with mouse clicks in many apps,
  so a plain key such as F8 is recommended.
* OCR uses Windows' built-in engine and only supports languages that have an OCR language pack installed
  (Settings → Time & language → Language & region). Copy-based selection works for every language.
* If a program has nothing selected, "copy" can copy something else (e.g. a selected file). Enable *restore clipboard*
  if that bothers you.
* API keys are stored as plain text in `%APPDATA%\SwiftTranslateWin\config.json`. Log: `app.log` in the same folder.
