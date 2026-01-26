#!/usr/bin/env python3
"""
Unified QGIS MCP HTTP Server - HTTP/SSE transport for MCP
Provides HTTP interface for integration with agent frameworks like Dify

Supports both:
1. QGIS operations (project manipulation, layer management, etc.)
2. QGIS API documentation extraction
"""

import json
import logging
import uuid
from typing import Dict, Any

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from sse_starlette import EventSourceResponse

from src.qgis_mcp.qgis_mcp_server import mcp
from src.qgis_mcp.extract_method_by_name import QGISMethodExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create extractor instance for API documentation
extractor = QGISMethodExtractor()

# Store active sessions: session_id -> write_stream
sessions: Dict[str, Any] = {}


async def handle_sse(request: Request) -> EventSourceResponse:
    """Handle SSE endpoint - establishes event stream for receiving messages from server"""
    session_id = str(uuid.uuid4())
    logger.info(f"New SSE connection from {request.client.host}, session: {session_id}")

    async def event_generator():
        """Generate SSE events from server messages"""
        # Create a memory stream for this session
        send_stream, receive_stream = anyio.create_memory_object_stream(100)
        sessions[session_id] = send_stream

        try:
            # Send endpoint event (Dify needs this to know where to POST)
            yield {
                "event": "endpoint",
                "data": f"/messages?sessionId={session_id}"
            }

            # Stream messages to client
            async for message in receive_stream:
                if message is None:
                    break

                yield {
                    "event": "message",
                    "data": json.dumps(message) if isinstance(message, dict) else message
                }

        except Exception as e:
            logger.error(f"Error in SSE stream: {e}", exc_info=True)
        finally:
            # Clean up session
            sessions.pop(session_id, None)
            logger.info(f"SSE connection closed for session: {session_id}")

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


async def handle_messages(request: Request) -> Response:
    """Handle POST /messages - receives messages from client"""
    try:
        # Get session ID from query parameter
        session_id = request.query_params.get("sessionId")

        if not session_id or session_id not in sessions:
            logger.error(f"Invalid or missing session ID: {session_id}, active: {list(sessions.keys())}")
            return JSONResponse(
                {"error": "Invalid or missing session ID"},
                status_code=400
            )

        # Get the JSON-RPC message from client
        message_data = await request.json()
        logger.info(f"Received message for session {session_id}: method={message_data.get('method')}, id={message_data.get('id')}")

        # Get the write stream for this session
        write_stream = sessions[session_id]

        # Process the message based on method
        method = message_data.get("method")
        msg_id = message_data.get("id")

        response_data = None

        if method == "initialize":
            response_data = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "qgis-mcp",
                        "version": "0.2.0"
                    }
                }
            }
            # Send via SSE
            await write_stream.send(response_data)

        elif method == "tools/list":
            # Get all tools from both FastMCP (QGIS ops) and API extractor
            tools_list = []

            # Get tools from FastMCP (QGIS operations)
            tools_list_result = await mcp.list_tools()
            for tool in tools_list_result:
                tools_list.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema
                })

            # Add API documentation extraction tools
            api_tools = [
                {
                    "name": "extract_qgis_method",
                    "description": "Extract QGIS API method documentation by name (e.g., QgsRasterBlock.noDataValue or just QgsRasterBlock)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "method_name": {
                                "type": "string",
                                "description": "QGIS method or class name (e.g., QgsRasterBlock.noDataValue or QgsSingleBandPseudoColorRenderer)"
                            }
                        },
                        "required": ["method_name"]
                    }
                },
                {
                    "name": "batch_extract_qgis_methods",
                    "description": "Batch extract multiple QGIS API methods documentation",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "method_names": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of QGIS method/class names"
                            }
                        },
                        "required": ["method_names"]
                    }
                }
            ]
            tools_list.extend(api_tools)

            response_data = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": tools_list
                }
            }
            # Send via SSE
            await write_stream.send(response_data)

        elif method == "tools/call":
            # Execute a tool
            tool_name = message_data["params"]["name"]
            arguments = message_data["params"].get("arguments", {})

            try:
                # Check if this is an API documentation tool
                if tool_name == "extract_qgis_method":
                    method_name = arguments.get("method_name")
                    if not method_name:
                        result_content = [{"type": "text", "text": "Error: Missing required parameter method_name"}]
                    else:
                        result = extractor.extract_by_method_name(method_name)
                        if result:
                            result_content = [{
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2)
                            }]
                        else:
                            result_content = [{
                                "type": "text",
                                "text": f"Method not found: {method_name}"
                            }]

                elif tool_name == "batch_extract_qgis_methods":
                    method_names = arguments.get("method_names", [])
                    if not method_names:
                        result_content = [{"type": "text", "text": "Error: Missing required parameter method_names"}]
                    else:
                        results = extractor.batch_extract(method_names)
                        summary = {
                            "total": len(method_names),
                            "success": len(results),
                            "failed": len(method_names) - len(results),
                            "failed_methods": []
                        }
                        # Calculate failed methods
                        extracted_names = set(r.get('full_method_name', r.get('class_name', '')) for r in results)
                        for name in method_names:
                            if name not in extracted_names:
                                summary["failed_methods"].append(name)

                        output = {
                            "summary": summary,
                            "results": results
                        }

                        result_content = [{
                            "type": "text",
                            "text": json.dumps(output, ensure_ascii=False, indent=2)
                        }]

                else:
                    # Use FastMCP's call_tool method for QGIS operations
                    result = await mcp.call_tool(tool_name, arguments)

                    # Convert result to MCP format
                    content = []
                    if result:
                        for item in result:
                            if hasattr(item, 'type') and hasattr(item, 'text'):
                                # Already in correct format
                                content.append({
                                    "type": item.type,
                                    "text": item.text
                                })
                            else:
                                # Convert to text
                                content.append({
                                    "type": "text",
                                    "text": str(item)
                                })

                    if not content:
                        content = [{"type": "text", "text": "Tool executed successfully"}]

                    result_content = content

                response_data = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": result_content
                    }
                }
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
                response_data = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }

            # Send via SSE
            await write_stream.send(response_data)

        elif method == "notifications/initialized":
            # Just acknowledge
            logger.info("Client initialized")
            return JSONResponse({"status": "ok"})

        else:
            response_data = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
            await write_stream.send(response_data)

        # Return 202 Accepted - response will come via SSE
        return JSONResponse({"status": "accepted"}, status_code=202)

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


async def health_check(request: Request) -> Response:
    """Health check endpoint"""
    return JSONResponse({
        "status": "ok",
        "service": "qgis-mcp",
        "version": "0.2.0"
    })


def create_app() -> Starlette:
    """Create and configure the Starlette application"""
    app = Starlette(
        debug=True,
        routes=[
            Route("/health", health_check, methods=["GET"]),
            Route("/sse", handle_sse, methods=["GET"]),
            Route("/messages", handle_messages, methods=["POST"]),
        ],
    )

    logger.info("Unified QGIS MCP HTTP Server initialized")
    logger.info("Available endpoints:")
    logger.info("  - GET  /health   : Health check")
    logger.info("  - GET  /sse      : Server-Sent Events stream")
    logger.info("  - POST /messages : Send messages to MCP server")

    return app


def main():
    """Run the HTTP server"""
    app = create_app()

    logger.info("Starting Unified QGIS MCP HTTP Server on http://0.0.0.0:8000")
    logger.info("Make sure QGIS with the MCP plugin is running on localhost:9876")
    logger.info("This server supports:")
    logger.info("  1. QGIS operations (project, layers, processing, etc.)")
    logger.info("  2. QGIS API documentation extraction")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )


if __name__ == "__main__":
    main()
