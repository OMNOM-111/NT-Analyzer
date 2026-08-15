#!/usr/bin/env python3
"""Every FK that references sf_users, its delete rule, and orphan-blocking rows."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
CURRENT={"canary":"/home/stratforge/canary-current","production":"/home/stratforge/current"}
PROGRAMS={"canary":"api","production":"api-app"}
def load_env(e):
    out=subprocess.check_output(["sudo","-n","supervisorctl","-c",
        "/home/stratforge/production_data/config/supervisord.conf","status"],text=True,timeout=30)
    pid=0
    for line in out.splitlines():
        p=line.split()
        if len(p)>=4 and p[0]==PROGRAMS[e] and p[1]=="RUNNING": pid=int(p[3].rstrip(","))
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(bytes([0])):
        if item and b"=" in item:
            k,_,v=item.partition(b"="); os.environ[k.decode()]=v.decode("utf-8","replace")
env=sys.argv[1]; load_env(env); sys.path.insert(0,CURRENT[env])
import psycopg
dsn=os.environ["STRATFORGE_DATABASE_URL"]
keep=sys.argv[2] if len(sys.argv)>2 else ""
with psycopg.connect(dsn, autocommit=True) as conn:
    conn.execute("SET stratforge.service_scope='global'")
    rows=conn.execute("""
      select con.conname, cl.relname as child, att.attname as col,
             con.confdeltype, con.convalidated
      from pg_constraint con
      join pg_class cl on cl.oid=con.conrelid
      join pg_class pr on pr.oid=con.confrelid
      join unnest(con.conkey) k(attnum) on true
      join pg_attribute att on att.attrelid=cl.oid and att.attnum=k.attnum
      where con.contype='f' and pr.relname='sf_users'
      order by cl.relname
    """).fetchall()
    print(f"{'constraint':38} {'table':22} {'column':14} on_delete validated")
    rules={'a':'NO ACTION','r':'RESTRICT','c':'CASCADE','n':'SET NULL','d':'SET DEFAULT'}
    for name,child,col,deltype,valid in rows:
        print(f"{name:38} {child:22} {col:14} {rules.get(deltype,deltype):9} {valid}")
    print("\nrows held by non-owner accounts:")
    for name,child,col,deltype,valid in rows:
        try:
            n=conn.execute(
                f"select count(*) from {child} c where c.{col} is not null "
                f"and c.{col} <> %s", (int(keep),)).fetchone()[0] if keep else None
            total=conn.execute(f"select count(*) from {child}").fetchone()[0]
            print(f"  {child:22}.{col:14} blocking={n} total={total}")
        except Exception as exc:
            print(f"  {child:22}.{col:14} ERROR {type(exc).__name__}: {str(exc)[:80]}")
