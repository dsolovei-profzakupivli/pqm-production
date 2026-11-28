"""Callback-local literal identities; all unrelated workflow callers retain legacy policy."""
from contextvars import ContextVar
from functools import wraps
import re
import sqlite3

_literal = ContextVar('pqm_edr_literal_identity', default=False)
_sql_tokens = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/)|\bDIGITS\s*(?=\()", re.I|re.S)

def literal(value):
    return '' if value is None else str(value)

def _sql(statement):
    if 'DIGITS' not in statement.upper():return statement
    return _sql_tokens.sub(lambda m:m.group(0) if m.group(1) else 'EDR_LITERAL',statement)

class Connection:
    """Callback-owned SQL adapter; global deterministic DIGITS never changes.

    EDR_LITERAL is pure text identity. Only explicit callback statements are
    rewritten; bound values, quoted data, other callers and connections stay intact.
    """
    def __init__(self, connection):
        self.connection=connection
        self.statements={}
        connection.create_function('EDR_LITERAL',1,literal,deterministic=True)
    def sql(self,statement):
        if statement not in self.statements:
            if len(self.statements)>=128:self.statements.clear()
            self.statements[statement]=_sql(statement)
        return self.statements[statement]
    def execute(self,sql,*args):return self.connection.execute(self.sql(sql),*args)
    def executemany(self,sql,*args):return self.connection.executemany(self.sql(sql),*args)
    def executescript(self,sql):
        # sqlite3.executescript implicitly COMMITs an existing transaction.
        # EDR callbacks must stay inside the caller's validated write transaction.
        # Use SQLite's own completeness parser for quoted semicolons and triggers.
        statement=''
        for character in sql:
            statement+=character
            if character==';' and sqlite3.complete_statement(statement):
                self.execute(statement);statement=''
        if statement.strip():self.execute(statement)
        return self
    def __getattr__(self,name):return getattr(self.connection,name)

def callbacks(connection, functions):
    """One bounded statement adapter per Apply, shared by its callbacks only."""
    proxy=Connection(connection)
    def bind(function):
        wrapped=callback(function)
        def call(con,*args,**kwargs):
            if con is not connection and con is not proxy:raise RuntimeError('EDR callback connection changed')
            return wrapped(proxy,*args,**kwargs)
        return call
    return {name:bind(function) for name,function in functions.items()}

def active():
    return _literal.get()

def code(value):
    text = '' if value is None else str(value)
    return text if active() else re.sub(r'\D', '', str(value or ''))

def callback(function):
    @wraps(function)
    def call(*args, **kwargs):
        token = _literal.set(True)
        try:
            if args and hasattr(args[0],'create_function') and not isinstance(args[0],Connection):
                args=(Connection(args[0]),*args[1:])
            return function(*args, **kwargs)
        finally:
            _literal.reset(token)
    return call
