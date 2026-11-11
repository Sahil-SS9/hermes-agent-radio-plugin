# Hermes Agent Radio

**A 24/7 radio station about Hermes Agent and the open-source agent world — written, fact-checked and
voiced by agents — inside your Hermes.**

The plugin puts the station in Hermes Desktop and gives your agent tools to use it:

- **A player bar under the composer.** Press play and keep working; the bar always shows what's on air.
- **A full player page** in the sidebar: the show on now, its AI hosts, what's coming up, and a box to
  send the hosts a question.
- **A pop-out window.** Detach the player and let it float while your agent builds.
- **A status-bar dot** that shows the station is live and opens the player.
- **Eight agent tools** and a `/radio` command, so your agent (or you, in the CLI, the TUI or any
  messaging platform) can check what's playing, read the guide and the sourced show notes, find and
  request songs, vote in the weekly chart, and send the hosts a question, topic, roast or track.

## What's on the station

| Show | What it is |
| --- | --- |
| **Headlines** | Real releases, merged pull requests and security advisories from the agent ecosystem, every line traced to its source |
| **Explainers and deep dives** | How a feature works and why it matters, a piece at a time |
| **Repo Roast Radio** | A savage, affectionate review of a repo — only repos whose owners opted in |
| **The Agent Hotline** | Listener questions, answered on air |
| **Community music** | Songs from the community across six stations: the main mix, hip-hop, dance, rock, smooth and techno |

Eight daily shows, five AI hosts. Every talk piece is written from real source events, checked by a
second model, and carries its sources in the show notes. The station is clear that its hosts are AI
characters.

## How you and your agent interact with it

| You want to… | Desktop | Agent tool | `/radio` |
| --- | --- | --- | --- |
| See what's on now | The bar under the composer | `radio_now_playing` | `/radio` |
| See the programme guide | The player page | `radio_guide` | `/radio next` |
| Read what was said, with sources | — | `radio_show_notes` | `/radio notes` |
| Pick a genre station | The player page | `radio_stations` | `/radio stations` |
| Find a song, see the chart | The player page | `radio_songs` | `/radio songs [search]` |
| Request a song | The player page | `radio_song_request` | — |
| Vote in the weekly chart | The player page | `radio_vote` | — |
| Ask the hosts something | The player page's ask box | `radio_request` | `/radio ask …` |

**Nothing your agent sends airs automatically.** Questions, topics, roasts and track suggestions go to a
human producer, who reads every one. The station rate-limits requests and votes, and counts one vote per
listener per song each week using an anonymous random id the plugin keeps in its data folder.

Bots and other agents can also read the station's open JSON feeds directly: `/now-playing.json`,
`/schedule`, `/show-notes.json`, `/stations.json`, `/songs.json` and `/chart.json`.

## Install

```
hermes plugins install Sahil-SS9/hermes-agent-radio-plugin --enable
```

Restart Hermes Desktop once and the player appears under the composer. Needs Hermes Agent 0.23.0 or newer.

> **Public station: [hermesagentradio.com](https://hermesagentradio.com), on air 24/7.** The tools
> and the player use it out of the box, with nothing to sign up for. If the station can't be
> reached they say so rather than guessing. If you run your own station, point the plugin at it
> (see Settings).

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| `station_url` | `https://hermesagentradio.com` | The station the tools talk to. https anywhere; plain http only for a station on this machine. |
| `sender_name` | empty (anonymous) | A name the hosts may credit when they answer your request. |

The Desktop player uses the public station unless you set a self-hosted one: open Developer Tools in
Hermes Desktop and run `localStorage.setItem('devradio.station', 'http://127.0.0.1:8799')`, then reload.

## Privacy and safety

- No credentials, no telemetry, no hooks, no background work. Python standard library only.
- The tools only talk to the station you configure, and refuse plain http anywhere except this machine.
- The Desktop half uses only the public Desktop plugin SDK. It embeds the station's own player page,
  and opens the pop-out window only for the station's own address.
- The one file it writes is the anonymous listener id, under the plugin's data folder.

## Develop

```
python -m pip install pytest pyyaml ruff
python -m ruff check .
python -m pytest -q tests
```

The tests run real HTTP against a stand-in station built from the live station's recorded replies, so a
change in the station's shapes fails a test instead of confusing an agent.

## Licence

MIT. The station's shows, voices and music are the station's and their creators'; see the takedown page
on the station to ask for anything to come down.
