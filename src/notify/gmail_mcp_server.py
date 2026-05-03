"""
Gmail MCP Server — exposes a send_email tool via stdio transport.

Uses Gmail SMTP with an App Password (no OAuth required).
Set credentials via environment variables:
    GMAIL_ADDRESS   your Gmail address
    GMAIL_APP_PASSWORD  16-char App Password from Google Account settings
"""

import os
import smtplib
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[2] / ".env")
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("gmail-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="send_email",
            description="Send an email via Gmail SMTP.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to":      {"type": "string",  "description": "Recipient email address"},
                    "subject": {"type": "string",  "description": "Email subject line"},
                    "body":    {"type": "string",  "description": "Plain-text email body"},
                    "references": {"type": "string", "description": "Message-ID to set in References header (optional)"},
                },
                "required": ["to", "subject", "body"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "send_email":
        raise ValueError(f"Unknown tool: {name}")

    gmail_address  = os.environ.get("GMAIL_ADDRESS", "")
    app_password   = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_address or not app_password:
        return [types.TextContent(
            type="text",
            text="ERROR: GMAIL_ADDRESS and GMAIL_APP_PASSWORD env vars must be set.",
        )]

    to       = arguments["to"]
    subject  = arguments["subject"]
    body     = arguments["body"]
    refs     = arguments.get("references", "")

    msg = MIMEMultipart("alternative")
    msg["From"]    = gmail_address
    msg["To"]      = to
    msg["Subject"] = subject
    msg["Date"]    = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    if refs:
        msg["References"] = refs

    msg.attach(MIMEText(body, "plain"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, to, msg.as_string())
        result = f"OK: email sent to {to} | subject: {subject}"
    except Exception as exc:
        result = f"ERROR: {exc}"

    return [types.TextContent(type="text", text=result)]


async def main():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
