# `Library.Steam`

What a program needs to appear in a person's Steam library. `import
Library.Steam;` brings in the whole group.

| Module | Owns |
|--------|------|
| `Library.Steam.SteamShortcuts` | `SteamShortcuts`, a profile's `shortcuts.vdf`, and `SteamShortcut`, one entry of it: its name, program, start directory, icon, number and picture names. |

```btrc
for file in SteamShortcuts.files(steamRoot) {
	SteamShortcuts shortcuts = SteamShortcuts.read(file);
	SteamShortcut chrome = shortcuts.ensure("Chrome", "/usr/bin/google-chrome", "", Platform.hostname());
	chrome.setIcon("/usr/share/icons/chrome.png");
	shortcuts.write(file);
	string portrait = chrome.picture(SteamShortcuts.pictures(file), STEAM_PICTURE_PORTRAIT) + ".png";
}
```

- **Nothing else changes.** An entry is kept as the bytes it was read from.
  `setIcon` and `setId` change that one field, and `ensure` leaves an entry
  that already has the name and the program as it is, so tags, play time and
  fields a newer Steam adds survive a rewrite.
- **Fail closed.** A file the reader cannot walk to its end (truncated, a
  field type it does not know, bytes after the end) throws and is never
  written back. A file that exists and cannot be read is not an empty one.
- **Write while Steam is closed.** A running Steam holds the file in memory
  and writes it again when it exits.
- **Numbers.** Steam derives a shortcut's number from its program and name,
  so two machines give the same shortcut the same number. Steam lists a
  person's other machines' shortcuts for Remote Play under their numbers, and
  a local shortcut whose number is taken gets a new one at every start, away
  from its pictures and controller layout. Passing the machine's name to
  `ensure` or `SteamShortcut.idOf` gives the shortcut a number of that
  machine's own. A number Steam chose itself is left alone.
- **Pictures.** `picture` names the file Steam looks for, less its extension
  (`png`, `jpg`, `jpeg` or `webp`), in the folder `SteamShortcuts.pictures`
  names. Copying a picture there is the caller's.
