---
name: network-diagram
description: Map a homelab as an editable draw.io diagram that shows the services, Docker networks, reverse proxy and DNS path from a public name to each container, built from the live Homelab inventory. Use when the user asks to map their homelab, show how a request reaches a service, or document the network layout.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Map a homelab network

This skill reads the inventory from Homelab, groups it into layers, and writes one `.drawio` file. The file shows the path from a public name to a container: DNS, the edge, the reverse proxy, then the service. It also shows which Docker network each service sits on.

The examples use `example.com` and the services `wiki`, `photos` and `notes`. Replace them with the user's values.

## Steps

### 1. Read the inventory (read only)

1. `homelab_modules`: which modules are on. Skip a layer whose module is off, and say so in the diagram's note.
2. `docker_containers` with `action` set to `list`, reading every page with `offset`. Record each container's name and state.
3. `docker_inventory` with `kind` set to `networks`. Record each Docker network and the containers on it.
4. `proxy_hosts` with `action` set to `list`, reading every page. Record each domain, its forward host, its forward port and whether SSL is on.
5. `dns_zones` with `action` set to `list`, then `dns_records` with `action` set to `list` for the zone. Record each name, type and target.
6. `proxy_access_lists` with `action` set to `list` when the user wants access controls shown.

### 2. Build the model

Write the model as a table before you draw. One row is one public path:

| Public name | DNS record | Edge | Proxy host | Forward target | Container | Docker network |
|---|---|---|---|---|---|---|
| wiki.example.com | CNAME to tunnel | Cloudflare Tunnel | wiki.example.com | `wiki-app:8080` | `wiki-app` | `proxy-net` |
| photos.example.com | A record | Port forward | photos.example.com | `photos:2283` | `photos` | `proxy-net` |
| notes.example.com | A record | Port forward | notes.example.com | `notes:3000` | `notes` | `proxy-net`, `db-net` |

Mark a container that appears on no public path as internal. Show it in its network, with no edge to the public side.

### 3. Lay out the layers

Draw left to right, one column per layer:

1. **Internet** (cloud shape)
2. **DNS** (the zone and its records)
3. **Edge** (tunnel, port forward or access list)
4. **Reverse proxy** (one box per proxy host, or one box for the proxy)
5. **Services** (one box per container, grouped by Docker network)

Draw each Docker network as a swimlane. Place each container inside the swimlane for its network. A container on two networks appears once, with an edge into each network's swimlane.

Draw one edge per path, in the direction of the request. Label each edge with the protocol and port: `HTTPS 443`, `HTTP 8080`.

### 4. Write the file

1. Name the file `homelab-network.drawio`, or the slug of the user's title, in the current working directory. Ask before overwriting an existing file.
2. Use the `diagram` skill's file structure, palette and quality check. Use the orthogonal edge style for every connection.
3. Add a note box in the bottom-left corner. The note lists the date of the inventory and each module that was off.
4. Report the path as a Markdown link.

## Rules for addresses

- Do not write LAN IP addresses, public IP addresses or hardware identifiers into the diagram. Label a subnet by its role, such as `lan` or `dmz`.
- Write a forward target as a container name and port, such as `wiki-app:8080`. A container name resolves inside its Docker network. A `localhost` target does not resolve from the proxy.
- If the user asks for addresses, confirm that the file leaves their machine before you add them.

## What the diagram shows

- Each public name, the record that points at it, and the path through the edge and proxy.
- Each service, its Docker networks and its state.
- Which services have no public name.
- Which proxy hosts have SSL off.

Keep the diagram to these facts. Do not add a layer that the inventory did not return.
