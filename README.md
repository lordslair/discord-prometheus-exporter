# discord-prometheus-exporter, the project :

TLDR; This is a Python rewrite of a another Discord metrics exporter: [nimarion/promcord][promcord]

This project started as I wanted to have a simple and lightweight container to export Discord stats into Prometheus.  
So discord-prometheus-exporter (DPE) was born

I found an amazing job done with *primcord*.  
Unfortunately for me, it's in Java - and I can't read a thing.  
So for updates or custom features, it was impossible to read or patch something on my side.

I decided to do a fork/rewrite of their job, and with the 1.0.x I achieved a 90% metrics coverage so far.

### Variables

To work properly, the scripts will require informations and credentials.  
We assume they are passed to the container in ENV variables.

Discord Server variables :
- `DISCORD_TOKEN`: Your BOT Token (Mandatory)

Exporter variables :
- `EXPORTER_PORT`: Listening port (Default: `8080`)
- `POLLING_INTERVAL`: Interval in seconds between Discord calls (Default: `10`)

ENV global variables :
- `LOGURU_LEVEL`: Minimal level for log output (Default: `DEBUG`)

### Output on container start

```
2022-09-20 11:52:17.994 | INFO     | __main__:<module>:13 - [Exporter][✓] System imports
2022-09-20 11:52:17.994 | INFO     | __main__:<module>:23 - [Exporter][✓] Listening on :8080
2022-09-20 11:52:17.995 | INFO     | __main__:<module>:24 - [Exporter][✓] Polling interval 10s
2022-09-20 11:52:18.088 | INFO     | __main__:<module>:70 - [Exporter][✓] Metrics defined
2022-09-20 11:52:18.090 | INFO     | __main__:<module>:82 - [Exporter][✓] Connection OK
```

### Exported metrics so far

```
# HELP discord_latency            The time in ms that discord took to respond.
# HELP discord_members_registered The number of connected members on a Guild.
# HELP discord_members_online     The number of online members on a Guild.
# HELP discord_bots_registered    The number of connected bots on a Guild.
# HELP discord_bots_online        The number of online bots on a Guild.
# HELP discord_boosts             The number of Server Boosts on a Guild.
# HELP discord_messages_total     The number of messages sent on a Guild by a Member.
# HELP discord_reactions_total    The number of messages sent on a Guild by a Member.
```

### Tech

I mainly used :

* [nimarion/promcord][promcord] as inspiration. Kudos for the amazing job!
* [docker/docker-ce][docker] to make it easy to maintain
* [kubernetes/kubernetes][kubernetes] to make everything smooth
* [Alpine][alpine] - probably the best/lighter base container to work with
* [Python] - as usual
* [Loguru][loguru] - an amazingly easy logger

And of course GitHub to store all these shenanigans.

### Installation

You can build the container yourself :
```
$ git clone https://github.com/lordslair/discord-prometheus-exporter
$ cd discord-prometheus-exporter/docker
$ docker build .
```

Or the latest build is available on docker hub :
```
$ docker pull lordslair/discord-prometheus-exporter:latest
latest: Pulling from lordslair/discord-prometheus-exporter
Digest: sha256:0dae89d2224b58357844492392b21eee56c73181fa9437100c4f9c4e5c00aec1
Status: Downloaded newer image for lordslair/discord-prometheus-exporter:latest
docker.io/lordslair/discord-prometheus-exporter:latest
```

For a Kubernetes (k8s) deployment, I added examples files :  
Of course, I encourage you to store Secrets to store your credentials
```
$ git clone https://github.com/lordslair/discord-prometheus-exporter
$ cd discord-prometheus-exporter/k8s
$ kubectl apply -f deployment.yaml
```

#### Grafana

You can import directly in Grafana the related Dashboard [here][dashboard].  
There is a preview:  

< INSERT SCREENSHOT HERE >

#### Disclaimer/Reminder

> Always store somewhere safe your BOT Token.  
> I won't take any blame if you mess up somewhere in the process =)  

### Why this rewrite

To have something:
- KISS
- Understandable by a Python newbie
- Easily maintainable  


### Resources / Performance

The container is quite light, as [Alpine][alpine] is used as base.  

```
$ docker images
REPOSITORY                              TAG       SIZE
lordslair/discord-prometheus-exporter   latest    86.2MB
```

On the performance topic, the container consumes about :
 - 0,1% of a CPU
 - 25MB of RAM

### Todos

 - Write a Docker (Compose) file for easy startup
 - Find a way to resume discord_messages_total without a DB

Nothing else, but I'm open to requests and PR.  

---
   [kubernetes]: <https://github.com/kubernetes/kubernetes>
   [docker]: <https://github.com/docker/docker-ce>
   [alpine]: <https://github.com/alpinelinux>
   [promcord]: <https://github.com/nimarion/promcord>
   [loguru]: <https://github.com/Delgan/loguru>
   [dashboard]: <https://github.com/lordslair/discord-prometheus-exporter/grafana/dashboard-DPE.json>
