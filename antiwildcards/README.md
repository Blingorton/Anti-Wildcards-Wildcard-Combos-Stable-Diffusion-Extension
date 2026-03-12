# Anti-Wildcards — SD Reforge Extension

Automatically appends negative prompt entries whenever a trigger phrase is found in your positive prompt.

---

## Installation

1. Copy `antiwildcards_extension.py` into your Reforge extensions folder:
   ```
   stable-diffusion-webui-reforge/extensions/antiwildcards/
   ```
   The file **must** be named something ending in `.py` inside its own subfolder.

   Final path should look like:
   ```
   extensions/
   └── antiwildcards/
       └── antiwildcards_extension.py
   ```

2. Place `antiwildcards.txt` in your wildcards folder:
   ```
   stable-diffusion-webui-reforge/extensions/wildcards/antiwildcards.txt
   ```
   > If you use a different wildcards extension (e.g. sd-dynamic-prompts), the wildcards folder path may differ. The extension looks for `wildcards/` one level up from the `extensions/` folder.

3. Restart Reforge.

---

## antiwildcards.txt Format

```
trigger phrase///negative prompt additions
```

- **Trigger phrase** — case-insensitive substring match against your positive prompt  
- **`///`** — separator (three forward slashes)  
- **Negative additions** — whatever you want appended to the negative prompt  
- Lines starting with `#` are comments and are ignored  
- Empty lines are ignored  

### Example

```
# antiwildcards.txt
chun-li from street fighter///hair buns,
cammy from street fighter///beret, red outfit,
landscape///people, person, figure,
photorealistic///anime, cartoon,
```

If your prompt is:
> `chun-li from street fighter with her hair in a ponytail`

And your negative prompt is:
> `blurry, low quality`

The generation will use:
> `blurry, low quality, hair buns,`

---

## UI

A collapsible **Anti-Wildcards** panel appears in both txt2img and img2img tabs:

- ✅ **Enable/disable** toggle  
- **↺ Reload** button — reloads `antiwildcards.txt` without restarting Reforge  
- Status line showing how many rules are currently loaded  

---

## Notes

- Rules are reloaded from disk at the **start of every batch** (so edits to the file take effect immediately without reloading the UI)
- Works with batch sizes > 1 and batch counts > 1
- Trigger matching is **substring**, so `"chun-li"` will match `"chun-li from street fighter doing a kick"`
