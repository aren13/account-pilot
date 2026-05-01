"""accountpilot people ..."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from accountpilot.core.db.connection import open_db
from accountpilot.core.identity import merge_people


@click.group("people")
def people_group() -> None:
    """Person/identifier management."""


def _db_option(f: Any) -> Any:
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


@people_group.command("list")
@_db_option
@click.option("--owners/--all", default=False)
def people_list(db_path: Path, owners: bool) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            sql = (
                "SELECT p.id, p.name, p.surname, p.is_owner, "
                "GROUP_CONCAT(i.kind || ':' || i.value) AS idents "
                "FROM people p LEFT JOIN identifiers i ON i.person_id=p.id "
                + ("WHERE p.is_owner=1 " if owners else "")
                + "GROUP BY p.id ORDER BY p.id"
            )
            async with db.execute(sql) as cur:
                rows = await cur.fetchall()
        for r in rows:
            full = f"{r['name']} {r['surname'] or ''}".strip()
            owner = "*" if r["is_owner"] else " "
            click.echo(f"#{r['id']} {owner} {full:<30} {r['idents'] or ''}")
    asyncio.run(_run())


@people_group.command("show")
@click.argument("person_id", type=int)
@_db_option
def people_show(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            async with db.execute(
                "SELECT name, surname, is_owner FROM people WHERE id=?", (person_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                click.echo(f"person id={person_id} not found")
                return
            click.echo(f"id: {person_id}")
            click.echo(f"name: {row['name']} {row['surname'] or ''}".rstrip())
            click.echo(f"owner: {'yes' if row['is_owner'] else 'no'}")
            async with db.execute(
                "SELECT kind, value, is_primary FROM identifiers WHERE person_id=?",
                (person_id,),
            ) as cur:
                idents = await cur.fetchall()
            click.echo("identifiers:")
            for i in idents:
                star = " *" if i["is_primary"] else ""
                click.echo(f"  - {i['kind']}: {i['value']}{star}")
    asyncio.run(_run())


@people_group.command("promote")
@click.argument("person_id", type=int)
@_db_option
def people_promote(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "UPDATE people SET is_owner=1, updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), person_id),
            )
            await db.commit()
        click.echo(f"promoted #{person_id} to owner")
    asyncio.run(_run())


@people_group.command("demote")
@click.argument("person_id", type=int)
@_db_option
def people_demote(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "UPDATE people SET is_owner=0, updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), person_id),
            )
            await db.commit()
        click.echo(f"demoted #{person_id} from owner")
    asyncio.run(_run())


@people_group.command("merge")
@click.option("--keep", "keep_id", type=int, required=True)
@click.option("--discard", "discard_id", type=int, required=True)
@_db_option
def people_merge(keep_id: int, discard_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await merge_people(db, keep_id=keep_id, discard_id=discard_id)
        click.echo(f"merged #{discard_id} into #{keep_id}")
    asyncio.run(_run())
