"""Optional local stdio MCP server; reads STATUS_API_URL only."""
import os
from typing import Literal, Any
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp_tools import StatusReader

reader = StatusReader(os.environ.get('STATUS_API_URL', 'http://127.0.0.1:9085/api/status'))
mcp = MCPServer('service-status', instructions='Read previously collected service connectivity records. These tools never run probes. Always consider generated and last timestamps. An unavailable API is unknown status, not a service outage.')
readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


@mcp.tool(annotations=readonly, structured_output=True)
def get_status() -> dict[str, Any]:
    """Get last observed state, latency and check time for each monitored service. No new probes are run."""
    return reader.get_status()


@mcp.tool(annotations=readonly, structured_output=True)
def get_history(hours: Literal[1, 24, 168] = 24, service: str = 'all') -> dict[str, Any]:
    """Read existing 1-hour, 24-hour or 7-day graph and observed issue ranges. Filter by service ID from get_status, or all."""
    return reader.get_history(hours, service)


@mcp.tool(annotations=readonly, structured_output=True)
def get_incidents(service: str = 'all') -> dict[str, Any]:
    """Read confirmed outage/recovery records for a service ID or all. Short transient failures are in get_history."""
    return reader.get_incidents(service)


if __name__ == '__main__':
    mcp.run(transport='stdio')
