from typing import Optional

from fastmcp import FastMCP

from cfmcp.cf_client import compact, get_account_id, get_cloudflare_client


def register_d1_tools(mcp: FastMCP) -> None:
    @mcp.tool
    async def list_d1_databases(name: Optional[str] = None) -> list[dict]:
        """List D1 (SQL) databases in the account, optionally filtered by exact name."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        databases = []
        async for database in client.d1.database.list(account_id=account_id, **compact(name=name)):
            databases.append(database.model_dump(exclude_none=True))
        return databases

    @mcp.tool
    async def create_d1_database(name: str) -> dict:
        """Create a D1 database. Use query_d1_database afterwards to run schema/DDL statements against it."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        database = await client.d1.database.create(account_id=account_id, name=name)
        return database.model_dump(exclude_none=True)

    @mcp.tool
    async def get_d1_database(database_id: str) -> dict:
        """Get details of a D1 database (table count, file size, version)."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        database = await client.d1.database.get(database_id, account_id=account_id)
        return database.model_dump(exclude_none=True)

    @mcp.tool
    async def delete_d1_database(database_id: str) -> dict:
        """Delete a D1 database and all its data."""
        client = get_cloudflare_client()
        account_id = await get_account_id()
        await client.d1.database.delete(database_id, account_id=account_id)
        return {"deleted": True, "database_id": database_id}

    @mcp.tool
    async def query_d1_database(database_id: str, sql: str, params: Optional[list[str]] = None) -> list[dict]:
        """Run a SQL statement against a D1 database (DDL, SELECT, INSERT/UPDATE/DELETE all go through this).
        `params` binds positional `?` placeholders in `sql`. Returns one result object per statement
        (only one, unless `sql` contains multiple `;`-separated statements), each with `success` and
        `results` (rows, for SELECT) or row-count metadata (for writes).
        """
        client = get_cloudflare_client()
        account_id = await get_account_id()
        results = []
        async for result in client.d1.database.query(
            database_id, account_id=account_id, sql=sql, **compact(params=params)
        ):
            results.append(result.model_dump(exclude_none=True))
        return results
