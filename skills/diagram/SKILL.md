---
name: diagram
description: Create an editable draw.io (.drawio) diagram file from a description of a system, flow, sequence or architecture. Use when the user wants a diagram they can open and edit in draw.io or diagrams.net. For an animated diagram, use dashmotion; for a map of a homelab network, use network-diagram.
license: MIT
source: https://github.com/seayniclabs/homelab-infra-mcp
author: Seaynic Labs
---

# Create a draw.io diagram

This skill writes a `.drawio` file. The file is plain XML that draw.io, diagrams.net and the VS Code draw.io extension open and edit.

## Steps

1. **Get the description.** Use the text the user gave. If they gave none, ask what the diagram shows and what type it is: flowchart, network, architecture, swimlane, sequence, entity relationship, org chart or free-form.
2. **Plan the layout.** List every shape, connection, label and group before you write XML. Count the shapes. Above 15 shapes, split the diagram into pages.
3. **Write the XML** using the structure and style rules below.
4. **Name and save the file.** Slugify the title: lowercase, hyphens for spaces, no symbols. "Network Topology" becomes `network-topology.drawio`. Save it in the current working directory. If the file exists, ask before overwriting.
5. **Report the path** as a Markdown link. Do not open the file.

## File structure

Every file starts with this skeleton. Each page has its own cell IDs.

```xml
<mxfile host="Homelab" modified="2026-10-27T00:00:00.000Z" agent="AI assistant" version="1.0" type="device">
  <diagram id="page1" name="Overview">
    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="850" background="#ffffff" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- shapes and edges go here, all with parent="1" or a container id -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Cell `0` is the invisible root. Cell `1` is the default layer. Both are required.

### Shape

```xml
<mxCell id="server_web1" value="Web server" style="rounded=1;whiteSpace=wrap;html=1;arcSize=10;fillColor=#dae8fc;strokeColor=#6c8ebf;" vertex="1" parent="1">
  <mxGeometry x="120" y="80" width="120" height="60" as="geometry"/>
</mxCell>
```

### Edge

```xml
<mxCell id="edge_web_to_db" value="SQL" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;labelBackgroundColor=#ffffff;" edge="1" parent="1" source="server_web1" target="db1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

### Group and container

Children use the container's ID as their `parent`. Child coordinates are relative to the container's top-left corner.

```xml
<mxCell id="zone_dmz" value="DMZ" style="swimlane;whiteSpace=wrap;html=1;startSize=30;fillColor=#f5f5f5;strokeColor=#666666;" vertex="1" parent="1">
  <mxGeometry x="100" y="60" width="320" height="200" as="geometry"/>
</mxCell>
<mxCell id="proxy" value="Reverse proxy" style="whiteSpace=wrap;html=1;" vertex="1" parent="zone_dmz">
  <mxGeometry x="20" y="50" width="120" height="60" as="geometry"/>
</mxCell>
```

### Escape HTML

When `html=1` is in the style, write labels with entities: `value="&lt;b&gt;Title&lt;/b&gt;&lt;br&gt;Detail"`.

## Shape styles

| Use | Style |
|---|---|
| Process | `whiteSpace=wrap;html=1;` |
| Rounded box | `rounded=1;whiteSpace=wrap;html=1;arcSize=10;` |
| Terminator (start, end) | `rounded=1;whiteSpace=wrap;html=1;arcSize=50;` |
| Decision | `shape=rhombus;whiteSpace=wrap;html=1;` |
| Data (input, output) | `shape=parallelogram;perimeter=parallelogramPerimeter;whiteSpace=wrap;html=1;` |
| Database | `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;stencilColors=1;size=15;` |
| Cloud or internet | `shape=cloud;whiteSpace=wrap;html=1;` |
| Document | `shape=document;whiteSpace=wrap;html=1;` |
| Note | `shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;` |
| Person (actor) | `shape=mxgraph.basic.person;whiteSpace=wrap;html=1;` |
| Swimlane | `swimlane;whiteSpace=wrap;html=1;startSize=30;` |
| Server | `shape=mxgraph.cisco.servers.standard_server;whiteSpace=wrap;html=1;` |
| Router | `shape=mxgraph.cisco.routers.router;whiteSpace=wrap;html=1;` |
| Firewall | `shape=mxgraph.cisco.firewalls.firewall;whiteSpace=wrap;html=1;` |

## Edge styles

| Use | Style |
|---|---|
| Straight arrow | `endArrow=classic;html=1;` |
| Orthogonal (architecture, network) | `edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;` |
| Curved | `curved=1;html=1;endArrow=classic;` |
| Dashed (optional or async) | `dashed=1;html=1;endArrow=classic;` |
| Two-way | `endArrow=classic;startArrow=classic;html=1;` |
| No arrow | `endArrow=none;html=1;` |

Arrow names: `classic`, `block`, `open`, `oval`, `diamond`, `dash`, `cross`, `none`, `ERone`, `ERmany`.

Use orthogonal edges for architecture and network diagrams. Use straight or curved edges for simple flowcharts.

## Palette

Use one palette per diagram. Use no more than four or five colors.

| Role | Fill | Stroke |
|---|---|---|
| Primary | `#dae8fc` | `#6c8ebf` |
| Success | `#d5e8d4` | `#82b366` |
| Warning | `#fff2cc` | `#d6b656` |
| Danger | `#f8cecc` | `#b85450` |
| Neutral | `#f5f5f5` | `#666666` |
| Accent | `#e1d5e7` | `#9673a6` |

## Layout

- Snap every coordinate to a multiple of 10.
- Keep at least 40 px between shapes. Use 80 to 120 px between columns and rows.
- Typical sizes: box 120 by 60, decision 80 by 80, database 60 by 80, cloud 120 by 80.
- Pick one flow direction, top to bottom or left to right, and keep it for the whole diagram.
- Align shapes on their centers.
- Give every cell a descriptive ID such as `server_web1` or `edge_web_to_db`. Never use bare numbers.
- Prefer swimlanes when the diagram shows who owns each step.
- Split a diagram above 15 shapes into pages, with an overview page first.

## Connection points

To control where an edge attaches, set `exitX`, `exitY`, `entryX` and `entryY` in the edge style. Top center is `0.5` and `0`. Bottom center is `0.5` and `1`. Left center is `0` and `0.5`. Right center is `1` and `0.5`.

## Quality check before you save

- Every cell ID is unique.
- Cells `0` and `1` are present.
- Every vertex has `vertex="1"` and an `mxGeometry`.
- Every edge has `edge="1"`, a `source` and a `target` that match vertex IDs.
- No two shapes overlap.
- Labels are short. Escaped HTML is valid.
- The XML is well formed: every tag closes, every attribute is quoted, every `&`, `<` and `>` in labels is escaped.
