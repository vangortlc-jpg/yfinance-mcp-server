"""
Yahoo Finance MCP Server — exposes yfinance data as MCP tools.

Covers: quotes, history, financials, analyst data, holders, options,
        commodities, forex, crypto, indices, and more.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

import mcp.server.stdio
import mcp.types as types
import pandas as pd
import yfinance as yf
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

os.environ.setdefault("CURL_CA_BUNDLE", "C:/cacert/cacert.pem")

logger = logging.getLogger(__name__)
server = Server("yfinance")


def _df_to_records(df: pd.DataFrame, limit: int = 100) -> list:
    if df is None or df.empty:
        return []
    df = df.head(limit).copy()
    df.index = df.index.astype(str)
    df.columns = [str(c) for c in df.columns]
    return json.loads(df.to_json(orient="table", date_format="iso", default_handler=str))["data"]


def _serialize(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        return _df_to_records(obj)
    if isinstance(obj, pd.Series):
        return json.loads(obj.to_json(default_handler=str))
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    if pd.isna(obj) if isinstance(obj, float) else False:
        return None
    return obj


TOOLS = [
    types.Tool(
        name="yf_quote",
        description="Get real-time quote snapshot for one or more symbols. Works for stocks (AAPL, 7203.T, 005930.KS), ETFs (SPY), indices (^GSPC), commodities (GC=F, CL=F), forex (USDJPY=X), crypto (BTC-USD).",
        inputSchema={
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Comma-separated ticker symbols, e.g. 'AAPL,MSFT,GC=F'"},
            },
            "required": ["symbols"],
        },
    ),
    types.Tool(
        name="yf_history",
        description="Get historical OHLCV price data. Supports intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo. Periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "period": {"type": "string", "description": "Data period, e.g. '1mo','1y','max'. Ignored if start/end provided.", "default": "1mo"},
                "interval": {"type": "string", "description": "Data interval, e.g. '1d','1wk','1mo'", "default": "1d"},
                "start": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD (optional)"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_info",
        description="Get comprehensive company/instrument info: sector, industry, market cap, PE, beta, dividend yield, 52-week range, description, employees, and 100+ fields.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_financials",
        description="Get financial statements: income_stmt, balance_sheet, cash_flow. Supports annual and quarterly. Also supports TTM (trailing twelve months).",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "statement": {"type": "string", "enum": ["income_stmt", "balance_sheet", "cash_flow"], "description": "Which financial statement"},
                "quarterly": {"type": "boolean", "description": "If true, return quarterly data instead of annual", "default": False},
                "ttm": {"type": "boolean", "description": "If true, return TTM (trailing twelve months) data", "default": False},
            },
            "required": ["symbol", "statement"],
        },
    ),
    types.Tool(
        name="yf_analyst",
        description="Get analyst data: price_targets, recommendations, upgrades_downgrades, earnings_estimate, revenue_estimate, growth_estimates, eps_trend.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "data_type": {
                    "type": "string",
                    "enum": ["price_targets", "recommendations", "upgrades_downgrades", "earnings_estimate", "revenue_estimate", "growth_estimates", "eps_trend", "eps_revisions", "earnings_dates"],
                    "description": "Type of analyst data",
                },
            },
            "required": ["symbol", "data_type"],
        },
    ),
    types.Tool(
        name="yf_holders",
        description="Get holder information: major_holders, institutional_holders, mutualfund_holders, insider_transactions, insider_purchases, insider_roster_holders.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "holder_type": {
                    "type": "string",
                    "enum": ["major_holders", "institutional_holders", "mutualfund_holders", "insider_transactions", "insider_purchases", "insider_roster_holders"],
                    "description": "Type of holder data",
                },
            },
            "required": ["symbol", "holder_type"],
        },
    ),
    types.Tool(
        name="yf_dividends",
        description="Get dividend history, stock splits, and capital gains for a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "data_type": {"type": "string", "enum": ["dividends", "splits", "actions", "capital_gains"], "default": "dividends"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_options",
        description="Get options chain data: list expiry dates, or get calls/puts for a specific expiry.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "expiry": {"type": "string", "description": "Expiry date YYYY-MM-DD. If omitted, returns list of available expiry dates."},
                "option_type": {"type": "string", "enum": ["calls", "puts", "both"], "default": "both", "description": "Which side of the chain"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_news",
        description="Get recent news articles related to a symbol.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_valuation",
        description="Get valuation measures time series (PE, PB, PS, EV/EBITDA, etc.) or SEC filings list.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "data_type": {"type": "string", "enum": ["valuation_measures", "sec_filings", "earnings_history", "calendar"], "default": "valuation_measures"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_compare",
        description="Compare multiple symbols side by side: current price, market cap, PE, dividend yield, 52-week range, YTD change.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Comma-separated ticker symbols, e.g. 'AAPL,MSFT,GOOGL'"},
            },
            "required": ["symbols"],
        },
    ),
    types.Tool(
        name="yf_screener_symbols",
        description="Lookup ticker symbols. Provide a reference of common symbols by category: us_stocks, japan_stocks, korea_stocks, commodities, forex, crypto, indices, sector_etfs.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["us_stocks", "japan_stocks", "korea_stocks", "commodities", "forex", "crypto", "indices", "sector_etfs"],
                    "description": "Category of symbols to list",
                },
            },
            "required": ["category"],
        },
    ),
    types.Tool(
        name="yf_calendar",
        description="Get upcoming events calendar: earnings dates, ex-dividend date, dividend date, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_history_metadata",
        description="Get metadata about a ticker's trading history: exchange, timezone, valid ranges, trading periods, first/last trade dates, instrument type, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="yf_batch_download",
        description="Download historical price data for multiple symbols at once using yf.download(). More efficient than calling yf_history individually. Returns OHLCV data.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbols": {"type": "string", "description": "Comma-separated ticker symbols, e.g. 'AAPL,MSFT,GOOGL'"},
                "period": {"type": "string", "description": "Data period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max", "default": "1mo"},
                "interval": {"type": "string", "description": "Data interval: 1d,1wk,1mo", "default": "1d"},
                "start": {"type": "string", "description": "Start date YYYY-MM-DD (optional)"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD (optional)"},
            },
            "required": ["symbols"],
        },
    ),
    types.Tool(
        name="yf_search",
        description="Search for ticker symbols by company name or keyword. Returns matching tickers with exchange info.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, e.g. 'Toyota', 'Samsung', 'gold etf'"},
                "max_results": {"type": "integer", "description": "Max results to return", "default": 10},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="yf_funds_data",
        description="Get fund-specific data for ETFs and mutual funds: top holdings, sector weights, bond ratings, fund performance, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "ETF or mutual fund ticker, e.g. 'SPY', 'QQQ', 'VFIAX'"},
                "data_type": {
                    "type": "string",
                    "enum": ["top_holdings", "sector_weights", "bond_ratings", "fund_performance", "fund_overview"],
                    "description": "Type of fund data",
                    "default": "top_holdings",
                },
            },
            "required": ["symbol"],
        },
    ),
]

SYMBOL_REFERENCE = {
    "us_stocks": {
        "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
        "NVDA": "NVIDIA", "META": "Meta", "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway",
        "JPM": "JPMorgan", "V": "Visa", "UNH": "UnitedHealth", "MA": "Mastercard",
        "HD": "Home Depot", "PG": "Procter & Gamble", "JNJ": "Johnson & Johnson",
        "XOM": "Exxon Mobil", "CVX": "Chevron", "LLY": "Eli Lilly", "AVGO": "Broadcom",
        "COST": "Costco", "WMT": "Walmart", "KO": "Coca-Cola", "PEP": "PepsiCo",
        "DIS": "Disney", "NFLX": "Netflix", "AMD": "AMD", "INTC": "Intel",
        "BA": "Boeing", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    },
    "japan_stocks": {
        "7203.T": "Toyota", "6758.T": "Sony", "9984.T": "SoftBank Group",
        "6861.T": "Keyence", "8306.T": "MUFG", "6902.T": "Denso",
        "7741.T": "HOYA", "6501.T": "Hitachi", "6367.T": "Daikin",
        "9432.T": "NTT", "6098.T": "Recruit", "8035.T": "Tokyo Electron",
        "4063.T": "Shin-Etsu Chemical", "7974.T": "Nintendo", "6594.T": "Nidec",
        "9433.T": "KDDI", "4519.T": "Chugai Pharma", "6723.T": "Renesas",
    },
    "korea_stocks": {
        "005930.KS": "Samsung Electronics", "000660.KS": "SK Hynix",
        "373220.KS": "LG Energy Solution", "207940.KS": "Samsung Biologics",
        "005380.KS": "Hyundai Motor", "006400.KS": "Samsung SDI",
        "035420.KS": "Naver", "035720.KS": "Kakao", "051910.KS": "LG Chem",
        "068270.KS": "Celltrion", "105560.KS": "KB Financial",
        "055550.KS": "Shinhan Financial", "012330.KS": "Hyundai Mobis",
        "066570.KS": "LG Electronics", "003550.KS": "LG",
    },
    "commodities": {
        "GC=F": "Gold", "SI=F": "Silver", "PL=F": "Platinum", "PA=F": "Palladium",
        "CL=F": "WTI Crude Oil", "BZ=F": "Brent Crude Oil", "NG=F": "Natural Gas",
        "HG=F": "Copper", "ALI=F": "Aluminum", "ZC=F": "Corn",
        "ZW=F": "Wheat", "ZS=F": "Soybeans", "KC=F": "Coffee",
        "SB=F": "Sugar", "CT=F": "Cotton", "CC=F": "Cocoa",
        "LBS=F": "Lumber", "LE=F": "Live Cattle", "HE=F": "Lean Hogs",
    },
    "forex": {
        "EURUSD=X": "EUR/USD", "USDJPY=X": "USD/JPY", "GBPUSD=X": "GBP/USD",
        "USDCHF=X": "USD/CHF", "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD",
        "NZDUSD=X": "NZD/USD", "USDCNY=X": "USD/CNY", "USDKRW=X": "USD/KRW",
        "USDHKD=X": "USD/HKD", "USDSGD=X": "USD/SGD", "USDTWD=X": "USD/TWD",
        "EURJPY=X": "EUR/JPY", "GBPJPY=X": "GBP/JPY", "EURGBP=X": "EUR/GBP",
    },
    "crypto": {
        "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "BNB-USD": "BNB",
        "SOL-USD": "Solana", "XRP-USD": "XRP", "ADA-USD": "Cardano",
        "DOGE-USD": "Dogecoin", "DOT-USD": "Polkadot", "AVAX-USD": "Avalanche",
        "MATIC-USD": "Polygon", "LINK-USD": "Chainlink", "LTC-USD": "Litecoin",
    },
    "indices": {
        "^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq Composite",
        "^RUT": "Russell 2000", "^VIX": "VIX", "^N225": "Nikkei 225",
        "^KS11": "KOSPI", "^HSI": "Hang Seng", "^FTSE": "FTSE 100",
        "^GDAXI": "DAX", "^FCHI": "CAC 40", "^STOXX50E": "Euro Stoxx 50",
        "^BVSP": "Bovespa", "^AXJO": "ASX 200", "^TNX": "US 10Y Yield",
        "^TYX": "US 30Y Yield", "^FVX": "US 5Y Yield", "^IRX": "US 3M T-Bill",
    },
    "sector_etfs": {
        "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care",
        "XLE": "Energy", "XLI": "Industrials", "XLP": "Consumer Staples",
        "XLY": "Consumer Discretionary", "XLB": "Materials", "XLU": "Utilities",
        "XLRE": "Real Estate", "XLC": "Communication Services",
        "SMH": "Semiconductors", "XBI": "Biotech", "KRE": "Regional Banks",
        "XHB": "Homebuilders", "TAN": "Solar", "LIT": "Lithium & Battery",
        "ARKK": "ARK Innovation", "GDX": "Gold Miners", "XOP": "Oil & Gas E&P",
    },
}


async def _handle_quote(args: dict) -> Any:
    symbols = [s.strip() for s in args["symbols"].split(",")]
    results = {}
    for sym in symbols:
        t = yf.Ticker(sym)
        fi = t.fast_info
        results[sym] = {
            "currency": fi.currency,
            "last_price": fi.last_price,
            "open": fi.open,
            "previous_close": fi.previous_close,
            "day_high": fi.day_high,
            "day_low": fi.day_low,
            "market_cap": fi.market_cap,
            "last_volume": fi.last_volume,
            "fifty_day_average": fi.fifty_day_average,
            "two_hundred_day_average": fi.two_hundred_day_average,
            "year_high": fi.year_high,
            "year_low": fi.year_low,
        }
    return results


async def _handle_history(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    kwargs = {"interval": args.get("interval", "1d")}
    if args.get("start"):
        kwargs["start"] = args["start"]
        if args.get("end"):
            kwargs["end"] = args["end"]
    else:
        kwargs["period"] = args.get("period", "1mo")
    df = t.history(**kwargs)
    return _df_to_records(df, limit=500)


async def _handle_info(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    return _serialize(t.info)


async def _handle_financials(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    stmt = args["statement"]
    quarterly = args.get("quarterly", False)
    ttm = args.get("ttm", False)

    if ttm:
        attr = f"ttm_{stmt.replace('income_stmt', 'income_stmt').replace('cash_flow', 'cash_flow')}"
        df = getattr(t, attr, None)
    elif quarterly:
        df = getattr(t, f"quarterly_{stmt}", None)
    else:
        df = getattr(t, stmt, None)

    return _df_to_records(df)


async def _handle_analyst(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    data_type = args["data_type"]
    result = getattr(t, data_type, None)
    return _serialize(result)


async def _handle_holders(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    result = getattr(t, args["holder_type"], None)
    return _serialize(result)


async def _handle_dividends(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    data_type = args.get("data_type", "dividends")
    result = getattr(t, data_type, None)
    return _serialize(result)


async def _handle_options(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    expiry = args.get("expiry")
    if not expiry:
        return {"expiry_dates": list(t.options)}
    chain = t.option_chain(expiry)
    option_type = args.get("option_type", "both")
    result = {}
    if option_type in ("calls", "both"):
        result["calls"] = _df_to_records(chain.calls, limit=200)
    if option_type in ("puts", "both"):
        result["puts"] = _df_to_records(chain.puts, limit=200)
    return result


async def _handle_news(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    return _serialize(t.news)


async def _handle_valuation(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    data_type = args.get("data_type", "valuation_measures")
    if data_type == "valuation_measures":
        result = getattr(t, "valuation_measures", None)
        if result is None:
            result = getattr(t, "valuation", None)
    else:
        result = getattr(t, data_type, None)
    return _serialize(result)


async def _handle_compare(args: dict) -> Any:
    symbols = [s.strip() for s in args["symbols"].split(",")]
    results = {}
    for sym in symbols:
        t = yf.Ticker(sym)
        info = t.info
        results[sym] = {
            "name": info.get("shortName"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "50d_avg": info.get("fiftyDayAverage"),
            "200d_avg": info.get("twoHundredDayAverage"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    return results


async def _handle_screener_symbols(args: dict) -> Any:
    category = args["category"]
    return SYMBOL_REFERENCE.get(category, {})


async def _handle_calendar(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    return _serialize(t.calendar)


async def _handle_history_metadata(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    return _serialize(t.history_metadata)


async def _handle_batch_download(args: dict) -> Any:
    symbols = [s.strip() for s in args["symbols"].split(",")]
    kwargs = {"interval": args.get("interval", "1d")}
    if args.get("start"):
        kwargs["start"] = args["start"]
        if args.get("end"):
            kwargs["end"] = args["end"]
    else:
        kwargs["period"] = args.get("period", "1mo")
    df = yf.download(symbols, **kwargs, group_by="ticker", threads=True)
    if len(symbols) == 1:
        return _df_to_records(df, limit=500)
    result = {}
    for sym in symbols:
        try:
            sym_df = df[sym].dropna(how="all")
            result[sym] = _df_to_records(sym_df, limit=500)
        except (KeyError, Exception):
            result[sym] = []
    return result


async def _handle_search(args: dict) -> Any:
    query = args["query"]
    max_results = args.get("max_results", 10)
    search = yf.Search(query, max_results=max_results)
    results = {"quotes": [], "news": []}
    if hasattr(search, "quotes"):
        results["quotes"] = _serialize(search.quotes)
    if hasattr(search, "news"):
        results["news"] = _serialize(search.news[:5])
    return results


async def _handle_funds_data(args: dict) -> Any:
    t = yf.Ticker(args["symbol"])
    data_type = args.get("data_type", "top_holdings")
    try:
        fd = t.funds_data
    except Exception:
        return {"error": f"{args['symbol']} does not appear to be a fund/ETF"}
    if data_type == "top_holdings":
        return _serialize(fd.top_holdings)
    elif data_type == "sector_weights":
        return _serialize(fd.sector_weights)
    elif data_type == "bond_ratings":
        return _serialize(fd.bond_ratings)
    elif data_type == "fund_performance":
        return _serialize(fd.fund_performance)
    elif data_type == "fund_overview":
        return _serialize(fd.fund_overview)
    return {"error": f"Unknown data_type: {data_type}"}


HANDLERS = {
    "yf_quote": _handle_quote,
    "yf_history": _handle_history,
    "yf_info": _handle_info,
    "yf_financials": _handle_financials,
    "yf_analyst": _handle_analyst,
    "yf_holders": _handle_holders,
    "yf_dividends": _handle_dividends,
    "yf_options": _handle_options,
    "yf_news": _handle_news,
    "yf_valuation": _handle_valuation,
    "yf_compare": _handle_compare,
    "yf_screener_symbols": _handle_screener_symbols,
    "yf_calendar": _handle_calendar,
    "yf_history_metadata": _handle_history_metadata,
    "yf_batch_download": _handle_batch_download,
    "yf_search": _handle_search,
    "yf_funds_data": _handle_funds_data,
}


@server.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any] | None) -> List[types.TextContent]:
    handler = HANDLERS.get(name)
    if not handler:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    try:
        result = await handler(arguments or {})
        text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if len(text) > 200_000:
            text = text[:200_000] + "\n... (truncated)"
        return [types.TextContent(type="text", text=text)]
    except Exception as e:
        logger.error(f"Error executing {name}: {e}", exc_info=True)
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def main() -> None:
    logger.info("Starting Yahoo Finance MCP server with %d tools", len(TOOLS))
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="yfinance",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def create_sse_app():
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="yfinance",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )
    return app


def main_sse() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    logger.info("Starting Yahoo Finance MCP SSE server on port %d with %d tools", port, len(TOOLS))
    app = create_sse_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
