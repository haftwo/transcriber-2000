# Using the app

- [Signing in](#signing-in)
- [Adding a stream](#adding-a-stream)
- [Finding a stream URL](#finding-a-stream-url)
- [Reading the transcript](#reading-the-transcript)
- [Searching](#searching)
- [Going back to a moment](#going-back-to-a-moment)
- [Listening live](#listening-live)
- [Playing back a moment](#playing-back-a-moment)
- [Downloading](#downloading)
- [Arranging, editing and stopping streams](#arranging-editing-and-stopping-streams)
- [Light and dark mode](#light-and-dark-mode)
- [Your account](#your-account)
- [On a phone](#on-a-phone)

## Signing in

Sign in with the username and password your admin gave you. You stay signed in for 30 days on that browser. If you've forgotten your password, ask an admin to reset it.

## Adding a stream

1. Click **Add** at the top of the **Streams** list.
2. Give it a name, for example `ABC Melbourne`.
3. Paste the stream URL.
4. Optionally set a language (`en`, `fr`, …). Leave it blank to use the default from Admin → Settings.
5. Save.

It starts straight away. The first lines appear after one chunk of audio, 15 seconds by default.

Streams are shared: everyone who can sign in sees the same list.

## Finding a stream URL

Most stations don't publish their stream address, but their web player uses one:

1. Open the station's web player in Chrome, Edge or Firefox.
2. Open developer tools (**F12** or **⌥⌘I**) and choose the **Network** tab.
3. Type `m3u8` in the filter box and press play.
4. Copy the URL of the playlist, usually ending `master.m3u8` or `playlist.m3u8`.

No `m3u8`? Try filtering for `mp3`, `aac` or `icecast`. Those direct streams work too.

Some stations use signed URLs that expire after a few hours. If a stream starts erroring, get a fresh URL and edit the stream.

## Reading the transcript

Pick a stream from the list to see its transcript. New lines appear at the bottom as they are transcribed. Each line shows the time it was spoken.

Scroll up to read earlier lines; more load as you go. While you're scrolled up, new lines collect below and a **↓ Back to live** button appears.

The dot next to each stream shows its state: green and pulsing while it's live, amber while it connects or reconnects, red if it has an error (hover the status to see it), grey when stopped.

## Searching

Type in the search box above the transcript to show only lines containing that text. Clear the box to return to the live view.

## Going back to a moment

Click the clock button next to the search box to **go to a date and time**. Pick a date and time, or use a shortcut such as **5 min ago** or **1 hour ago**. The transcript jumps to that moment and the player opens on the recording there, if it's still kept.

Click **↓ Back to live** to return.

## Listening live

Click **Listen** to play the stream in your browser alongside the transcript. Some stations block playback from other websites. Transcription still works for those, because the server fetches the audio itself.

## Playing back a moment

Every stream is recorded while it runs, so you can hear any line again.

- **Click a line** to open the player at the bottom of the page. It loads that line plus 30 seconds either side, shows the waveform, and plays from the start of the line. The line being heard is highlighted as it plays.
- **Shift-click** another line, or drag-select across several lines, to cover a longer passage.
- **Click the waveform** to jump to that point.
- **Space** plays and pauses. **Esc** closes the player.
- **« Earlier** and **Later »** add 30 seconds to either end, up to 15 minutes in total.
- **Download** saves exactly what the player shows as an MP3.

A line can't be played if its audio has expired (recordings are kept 7 days by default) or if it was transcribed while recording was off. A clip can't span a dropout: each reconnect starts a new recording.

## Downloading

Open the **⋯** menu at the top of a stream and choose a download:

- **Text · last 24 hours** or **Text · last 7 days**: one line per sentence, each with its date and time
- **Subtitles (.srt) · last 24 hours**: timed from the first line

Times use the server's time zone (the container's `TZ` setting).

## Arranging, editing and stopping streams

- **Reorder:** drag streams in the list. The order is saved for everyone.
- **Stop / Start:** the button next to **Listen**. A stopped stream keeps its transcript and recordings but stops listening.
- **Edit stream** (⋯ menu): change its name, URL or language. Changing the URL or language restarts it.
- **Restart** (⋯ menu): reconnect now, for example after fixing an expired URL.
- **Delete stream** (⋯ menu): removes the stream with its transcript and recordings. This can't be undone.

## Light and dark mode

Open the menu under your username (top right) and choose a **Theme**:

- **Auto** follows your device's light or dark setting. This is the default.
- **Light** or **Dark** always uses that look.

The same switch is under the card on the sign-in page. Your choice is saved in that browser, so each device can have its own.

## Your account

From the menu under your username:

- **Change password**: at least 8 characters.
- **Sign out**.

## On a phone

The app works in a phone browser. Tap the menu button at the top left to show the stream list.

To put it on your home screen:

- **iPhone / iPad (Safari):** Share → **Add to Home Screen**
- **Android (Chrome):** ⋮ → **Add to Home screen** or **Install app**

It opens full-screen with the app icon.
