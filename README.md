# QGISMCP - QGIS Model Context Protocol Integration

QGISMCP connects [QGIS](https://qgis.org/) to AI agents through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs/getting-started/intro), allowing AI systems to directly interact with and control QGIS. This integration enables prompt assisted project creation, layer loading, code execution and more.

This project is strongly based on the [BlenderMCP](https://github.com/ahujasid/blender-mcp/tree/main) project by [Siddharth Ahuja](https://x.com/sidahuj)

## Features

- **Two-way communication**: Connect AI agents to QGIS through a socket-based server.
- **Multiple transport modes**: Support both stdio (for Claude Desktop) and HTTP/SSE (for Dify and other frameworks).
- **Unified MCP Server**: Single server supporting both QGIS operations and API documentation extraction.
- **Project manipulation**: Create, load and save projects in QGIS.
- **Layer manipulation**: Add and remove vector or raster layers to a project.
- **Execute processing**: Execute processing algorithms ([Processing Toolbox](https://docs.qgis.org/3.40/en/docs/user_manual/processing/toolbox.html)).
- **Code execution**: Run arbitrary Python code in QGIS from AI agents. Very powerful, but also be very cautious using this tool.
- **API Documentation**: Extract QGIS API documentation for methods and classes directly from official documentation.

## Components

The system consists of three main components:

1. **[QGIS plugin](/qgis_mcp_plugin/)**: A QGIS plugin that creates a socket server within QGIS to receive and execute commands.
2. **[MCP Server (stdio)](/src/qgis_mcp/qgis_mcp_server.py)**: A Python server that implements Model Context Protocol over stdio for Claude Desktop.
3. **[Unified MCP Server (HTTP)](/mcp_server.py)**: A single HTTP/SSE server supporting both QGIS operations and API documentation extraction for integration with agent frameworks like Dify.

## Installation

### Prerequisites

- QGIS 3.X (only tested on 3.22)
- Claude desktop
- Python 3.10 or newer
- **uv** package manager (required for this project)

If you're on Mac, please install uv as:

```bash
brew install uv
```

On Windows PowerShell:

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Otherwise, follow installation instructions at: [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

**⚠️ Do not proceed before installing UV**

### Download code

Download this repo to your computer. You can clone it with:

```bash
git clone git@github.com:jjsantos01/qgis_mcp.git
```

### QGIS plugin

You need to copy the folder [qgis_mcp_plugin](/qgis_mcp_plugin/) and its content on your QGIS profile plugins folder.

You can get your profile folder in QGIS going to menu `Settings` -> `User profiles` -> `Open active profile folder` Then, go to `Python/plugins` and paste the folder `qgis_mcp_plugin`.

> On a Windows machine the plugins folder is usually located at: `C:\Users\USER\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins` 

and on MacOS: `~/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins`

 Then close QGIS and open it again. Go to the menu option `Plugins` > `Installing and Managing Plugins`, select the `All` tab and search for "QGIS MCP", then mark the QGIS MCP checkbox.

### Claude for Desktop Integration

Go to `Claude` > `Settings` > `Developer` > `Edit Config` > `claude_desktop_config.json` to include the following:

> If you can't find the "Developers tab" or the `claude_desktop_config.json` look at this [documentation](https://modelcontextprotocol.io/quickstart/user#2-add-the-filesystem-mcp-server).

```json
{
    "mcpServers": {
        "qgis": {
            "command": "uv",
            "args": [
                "--directory",
                "/ABSOLUTE/PATH/TO/PARENT/REPO/FOLDER/qgis_mcp/src/qgis_mcp",
                "run",
                "qgis_mcp_server.py"
            ]
        }

    }
}
```

## Usage

## Usage

### Starting the QGIS Server

1. In QGIS, go to `plugins` > `QGIS MCP` > `QGIS MCP`
    ![plugins menu](/assets/imgs/qgis-plugins-menu.png)
2. Click "Start Server"
    ![start server](/assets/imgs/qgis-mcp-start-server.png)

### Option 1: Using with Claude Desktop (stdio mode)

Once the QGIS plugin server is running and the Claude config file has been set up, you will see a hammer icon with tools for the QGIS MCP.

![Claude tools](assets/imgs/claude-available-tools.png)

### Option 2: Using with Dify or other HTTP-based frameworks

For agent frameworks like Dify that communicate via HTTP, use the unified HTTP server mode:

1. Make sure QGIS plugin server is running (see "Starting the QGIS Server" above)

2. Install dependencies using uv:
```bash
cd /path/to/qgis_mcp
uv sync
```

3. Start the unified HTTP server:
```bash
uv run python mcp_server.py
```

The server will start on `http://0.0.0.0:8000` with the following endpoints:
- `GET /health` - Health check endpoint
- `GET /sse` - Server-Sent Events stream for receiving MCP messages
- `POST /messages` - Send messages to the MCP server

4. Configure Dify or your agent framework to connect to:
   - **Base URL**: `http://your-server-ip:8000`
   - **Transport**: SSE (Server-Sent Events)

The unified HTTP server supports:
- All QGIS operation tools (project, layers, processing, etc.) - same as stdio version
- QGIS API documentation extraction tools:
  - `extract_qgis_method` - Extract documentation for a single method or class
  - `batch_extract_qgis_methods` - Batch extract documentation for multiple methods/classes

### Starting the Connection

Once the config file has been set on Claude, and the server is running on QGIS, you will see a hammer icon with tools for the QGIS MCP.

![Claude tools](assets/imgs/claude-available-tools.png)

#### Tools

**QGIS Operations:**
- `ping` - Simple ping command to check server connectivity
- `get_qgis_info` - Get QGIS information about the current installation
- `load_project` - Load a QGIS project from the specified path
- `create_new_project` - Create a new project and save it
- `get_project_info` - Get current project information
- `add_vector_layer` - Add a vector layer to the project
- `add_raster_layer` - Add a raster layer to the project
- `get_layers` - Retrieve all layers in the current project
- `remove_layer` - Remove a layer from the project by its ID
- `zoom_to_layer` - Zoom to the extent of a specified layer
- `get_layer_features` - Retrieve features from a vector layer with an optional limit
- `execute_processing` - Execute a processing algorithm with the given parameters
- `save_project` - Save the current project to the given path
- `render_map` - Render the current map view to an image file
- `execute_code` - Execute arbitrary PyQGIS code provided as a string

**QGIS API Documentation (HTTP/SSE only):**
- `extract_qgis_method` - Extract QGIS API method documentation by name (e.g., `QgsRasterBlock.noDataValue` or just `QgsRasterBlock`)
- `batch_extract_qgis_methods` - Batch extract documentation for multiple methods/classes

### Example Commands

This is the example I used for the [demo](https://x.com/jjsantoso/status/1900293848271667395):

```plain
You have access to the tools to work with QGIS. You will do the following:
	1. Ping to check the connection. If it works, continue with the following steps.
	2. Create a new project and save it at: "C:/Users/USER/GitHub/qgis_mcp/data/cdmx.qgz"
	3. Load the vector layer: ""C:/Users/USER/GitHub/qgis_mcp/data/cdmx/mgpc_2019.shp" and name it "Colonias".
	4. Load the raster layer: "C:/Users/USER/GitHub/qgis_mcp/data/09014.tif" and name it "BJ"
	5. Zoom to the "BJ" layer.
	6. Execute the centroid algorithm on the "Colonias" layer. Skip the geometry check. Save the output to "colonias_centroids.geojson".
	7. Execute code to create a choropleth map using the "POB2010" field in the "Colonias" layer. Use the quantile classification method with 5 classes and the Spectral color ramp.
	8. Render the map to "C:/Users/USER/GitHub/qgis_mcp/data/cdmx.png"
	9. Save the project.
```
