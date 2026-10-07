# discord-prometheus-exporter, the project :

TLDR; This is a Python rewrite of another Discord metrics exporter: [nimarion/promcord][promcord]

This project started as I wanted to have a simple and lightweight container to export Discord stats into Prometheus.  
So discord-prometheus-exporter (DPE) was born

I found an amazing job done with *promcord*.  
Unfortunately for me, it's in Java - and I can't read a thing.  
So for updates or custom features, it was impossible to read or patch something on my side.

I decided to do a fork/rewrite of their job, and with the 1.0.x I achieved a 90% metrics coverage so far.

### Discord BOT setup

The exporter connects to Discord as a BOT, so you need one: create it in the [Discord Developer Portal][devportal], and invite it on the servers (Guilds) you want to monitor.

In the BOT settings, enable these two **Privileged Gateway Intents**, or Discord refuses the connection (`PrivilegedIntentsRequired` error at startup):
- `SERVER MEMBERS INTENT`
- `PRESENCE INTENT`

### Variables

To work properly, the exporter requires a few settings and credentials.  
They are passed to the container as ENV variables.

| Variable | Description | Default |
|---|---|---|
| `DISCORD_TOKEN` | Your BOT Token (**Mandatory**, the exporter exits without it) | - |
| `EXPORTER_PORT` | Prometheus metrics listening port (on `/metrics`) | `8080` |
| `HEALTH_PORT` | Healthcheck listening port (on `/healthz`) | `8081` |
| `POLLING_INTERVAL` | Interval in seconds between two metrics updates | `10` |
| `PERSIST_FILE` | Complete path to the persistence file (see [Persistence](#persistence)) | None (disabled) |
| `PERSIST_TIMER` | Interval in seconds between two persistence saves | `60` |
| `LOGURU_LEVEL` | Minimal level for log output | `DEBUG` |

### Output on container start

```
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - DISCORD_TOKEN: MTA2...6789
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - EXPORTER_PORT: 8080
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - HEALTH_PORT: 8081
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - PERSIST_FILE: /data/counters.json
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - PERSIST_TIMER: 60
2026-10-07 19:45:50.363 | DEBUG    | variables:log_env_vars:33 - POLLING_INTERVAL: 10
2026-10-07 19:45:50.370 | INFO     | metrics:<module>:54 - [Exporter][✓] Metrics defined
2026-10-07 19:45:52.112 | INFO     | exporter:on_ready:156 - [Exporter][✓] Connected as MyBot#1234 (2 guilds)
```

The token is never written in full: only its first and last 4 characters, to check which one is used.  
The `Connected as` line comes once Discord is connected and the Guilds are loaded (and again after a reconnection).

### Exported metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `discord_latency` | Gauge | - | The Discord WebSocket latency (heartbeat round trip), in **seconds** |
| `discord_members_registered` | Gauge | `guild` | The number of members (bots excluded) on a Guild |
| `discord_members_online` | Gauge | `guild` | The number of online members on a Guild |
| `discord_bots_registered` | Gauge | `guild` | The number of bots on a Guild |
| `discord_bots_online` | Gauge | `guild` | The number of online bots on a Guild |
| `discord_boosts` | Gauge | `guild` | The number of Server Boosts on a Guild |
| `discord_messages_total` | Counter | `guild`, `member` | The number of messages sent on a Guild by a Member |
| `discord_reactions_total` | Counter | `guild`, `member` | The number of reactions added on a Guild by a Member |

Good to know:
- `guild` and `member` labels are the Guild and Member names.
- "Online" means any status but offline (online, idle, do not disturb).
- Messages and reactions from bots, or in direct messages to the BOT, are not counted.
- Reactions are counted on any message, old ones included.
- `discord_latency` stays at its last known value while the BOT is not connected (`0` before the first connection).
- When the BOT leaves a Guild (or a Guild is renamed), its Gauges are removed within one `POLLING_INTERVAL`. Counters are kept.

### Healthcheck

`/healthz` (on `HEALTH_PORT`) reports the Discord connection state, to be used by liveness/readiness probes:

| Response | Meaning |
|---|---|
| `200 OK` | Connected to Discord, metrics are up to date |
| `503 NOT_READY` | Starting, or reconnecting to Discord |
| `503 DISCONNECTED` | The Discord connection is closed |

If the BOT can't log into Discord (wrong token, Discord unreachable...), the exporter exits with an error code, so the container gets restarted.

### Installation

You can build the container yourself :
```
$ git clone https://github.com/lordslair/discord-prometheus-exporter
$ cd discord-prometheus-exporter
$ docker build -t discord-prometheus-exporter .
```

Or the latest build is available on docker hub :
```
$ docker pull lordslair/discord-prometheus-exporter:latest
```

Images tags:
- `latest`, `X.Y.Z`, `X.Y`: releases
- `edge`: the latest build of the `main` branch

Then run it:
```
$ docker run -d \
    -e DISCORD_TOKEN='<YOUR_DISCORD_BOT_TOKEN>' \
    -p 8080:8080 \
    -p 8081:8081 \
    lordslair/discord-prometheus-exporter:latest
```

And add it to your Prometheus scrape configuration:
```
scrape_configs:
  - job_name: discord
    static_configs:
      - targets: ['<EXPORTER_HOST>:8080']
```

#### Kubernetes

For a Kubernetes (k8s) deployment, I added an example file (with probes and persistence):
```
$ git clone https://github.com/lordslair/discord-prometheus-exporter
$ cd discord-prometheus-exporter/k8s
$ kubectl apply -f deployment.yaml
```

The example has the token in plain text, to keep it simple.  
I encourage you to store it in a Secret instead:
```
$ kubectl -n monitoring create secret generic discord-prometheus-exporter \
    --from-literal=DISCORD_TOKEN='<YOUR_DISCORD_BOT_TOKEN>'
```
And use it in `deployment.yaml`:
```
        - name: DISCORD_TOKEN
          valueFrom:
            secretKeyRef:
              name: discord-prometheus-exporter
              key: DISCORD_TOKEN
```

#### Persistence

Prometheus Counters (messages and reactions) restart from zero with the exporter.  
To keep them across restarts, set `PERSIST_FILE`: they are saved in it every `PERSIST_TIMER` seconds, and when the exporter stops.

The file needs to be on a volume to be useful:
- Kubernetes: the example uses an `emptyDir`, which survives container restarts, but not the Pod deletion (new deployments included). Use a `PersistentVolumeClaim` to keep the Counters across those.
- Docker: mount a host directory, like `-v /srv/dpe:/data -e PERSIST_FILE=/data/counters.json`.  
  The exporter runs as UID `1000`, which needs write access to it.

NB: The persistence is not enabled by default, to be as light as possible.

#### Grafana

You can import directly in Grafana the related Dashboard [here][dashboard].

#### Perses

You can import directly in [Perses][perses] the related Dashboard [here][perses-dashboard].

#### Disclaimer/Reminder

> Always store somewhere safe your BOT Token.  
> I won't take any blame if you mess up somewhere in the process =)  

### Development

The code is in `code/`, the tests in `tests/` (Discord is faked, no token or network needed).

To run the tests and the linter locally (Python 3.13, like the container):
```
$ pip install -r requirements.txt -r requirements-tests.txt -r requirements-lint.txt
$ pytest
$ flake8 code tests
```

Dependencies are pinned with [pip-tools][piptools]: edit `requirements.in`, then regenerate `requirements.txt` with
```
$ pip-compile --strip-extras requirements.in
```

The GitHub Actions pipelines:
- **Pipeline Tests**: lint + tests + image build on every push and Pull Request to `main`, then pushes the `edge` image (`main` pushes only). It can also be run manually on any branch, as a dry run (nothing is pushed).
- **Pipeline Release**: lint + tests, then pushes the release images, on every `v*` tag.

### Tech

I mainly used :

* [nimarion/promcord][promcord] as inspiration. Kudos for the amazing job!
* [Pycord][pycord] - to talk to Discord
* [prometheus/client_python][prometheus_client] - to export the metrics
* [docker/docker-ce][docker] to make it easy to maintain
* [kubernetes/kubernetes][kubernetes] to make everything smooth
* [Alpine][alpine] - probably the best/lighter base container to work with
* [Python] - as usual
* [Loguru][loguru] - an amazingly easy logger

And of course GitHub to store all these shenanigans.

### Why this rewrite

To have something:
- KISS
- Understandable by a Python newbie
- Easily maintainable  


### Resources / Performance

The container is quite light, as [Alpine][alpine] is used as base:
- about 31MB to download
- about 79MB on disk

On the performance topic, the container consumes about :
 - 0,1% of a CPU
 - 25MB of RAM

### Todos

 - Write a Docker (Compose) file for easy startup

Nothing else, but I'm open to requests and PR.  

---
   [kubernetes]: <https://github.com/kubernetes/kubernetes>
   [docker]: <https://github.com/docker/docker-ce>
   [alpine]: <https://github.com/alpinelinux>
   [promcord]: <https://github.com/nimarion/promcord>
   [loguru]: <https://github.com/Delgan/loguru>
   [pycord]: <https://github.com/Pycord-Development/pycord>
   [prometheus_client]: <https://github.com/prometheus/client_python>
   [piptools]: <https://github.com/jazzband/pip-tools>
   [devportal]: <https://discord.com/developers/applications>
   [python]: <https://www.python.org>
   [dashboard]: <dashboards/grafana.json>
   [perses]: <https://perses.dev>
   [perses-dashboard]: <dashboards/perses.json>
