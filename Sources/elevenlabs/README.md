# ElevenLabs

Voices and speech from [ElevenLabs](https://elevenlabs.io) as process nodes – e.g. a process that writes a video script
and then records its narration. Samples and the finished audio files play right in Theron's chat.

**Setup:** Settings → Plugins → ElevenLabs → *Settings …*: your **API key** (elevenlabs.io → Developers → API Keys →
Create API key; it needs *Text to Speech*, *Voices* read and *User* read for the credits). **Test** checks the key and
shows your plan, the characters left and how many voices the account has.

## 🎙 Choose voice

| Mode | What happens |
|---|---|
| **Manual** | The chat lists the voices – name, gender, age, accent, description and a **▶ Sample** each. Answer with a number, a name or in your own words (“the deep male one”). |
| **Automatic** | The node picks the voice that fits the mood of the incoming text best, within your **preselection**. |
| **Fixed** | The voice you pick in the node. |

**Preselection** (manual and automatic), e.g. `female, German, warm`: narrows the list – German words work too
(`weiblich, deutsch`). After the choice the chat shows the voice with **▶ Listen to the sample**. The node hands the voice
on to *Generate speech*. Outputs: **Voice** and **Error** (no key, no voices, a fixed voice that is gone …).

## 🔊 Generate speech

The AI takes what is spoken out loud from the incoming text (the narration of a script – no scene notes or headings),
splits it into parts (one per scene or section) and ElevenLabs speaks each part into a file.

| Field | |
|---|---|
| **Emotions (v3 audio tags)** | On: Eleven v3 with tags like `[excited]`, `[whispers]`, `[laughs]` where they help. A voice that can't speak v3 is spoken with Multilingual v2, without the tags (the chat says so). |
| **Model without emotions** | Multilingual v2 (best), Turbo v2.5 (fast) or Flash v2.5 (fastest, half the credits) |
| **Voice** | empty = the one *Choose voice* handed over |
| **Folder** | relative to the project's workspace (default `audio/`) – files `<task>-<nr>-<part>.mp3` |
| **Format** | mp3 (128 / 192 kbit/s, 32 kbit/s), pcm → `.wav`, opus |
| **Language** | an ISO code like `de` – only when ElevenLabs guesses wrong |

Before speaking the node checks your credits; not enough → **Error** with how many characters are needed and left.
Running out in the middle (or any other ElevenLabs error) also goes to **Error**, naming the files already made.
On success the output **Audio files** hands on a list of the paths (and `AUDIO_FILES:` one per line), and the chat shows
each file with ▶.

## In the chat

▶ plays, ■ stops – one sound at a time, with the computer's own player (macOS `afplay`, Windows' media player,
Linux `ffplay` / `mpg123` / PipeWire / PulseAudio). Every path to an audio file that exists, in any chat message, gets
a ▶ as well. Samples are downloaded once and kept in the plugin's folder.

Needs Theron 0.17.0. Permissions: network (ElevenLabs), AI (choosing voices, preparing the text), files (the audio files
in the project's folder), UI.
