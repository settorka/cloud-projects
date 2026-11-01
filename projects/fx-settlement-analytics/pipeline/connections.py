"""Windows client libraries for local SQL Server and SSAS; credentials stay in Windows."""

import sys
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def clients():
    if sys.platform != "win32":
        raise RuntimeError(
            "Run the backend on the Windows VM; access the dashboard from your browser."
        )
    import clr

    clr.AddReference("System.Data")
    assemblies = sorted(
        Path(
            "C:/Windows/Microsoft.NET/assembly/GAC_MSIL/Microsoft.AnalysisServices.AdomdClient"
        ).glob("**/Microsoft.AnalysisServices.AdomdClient.dll")
    )
    if not assemblies:
        raise RuntimeError("ADOMD.NET client library is missing")
    clr.AddReference(str(assemblies[-1]))
    from Microsoft.AnalysisServices.AdomdClient import AdomdConnection
    from System.Data import SqlDbType
    from System.Data.SqlClient import SqlConnection
    from System.Globalization import CultureInfo

    return SqlConnection, AdomdConnection, SqlDbType, CultureInfo.InvariantCulture


def rows(reader):
    result = []
    columns = [
        reader.GetName(i).rsplit("[", 1)[-1].rstrip("]")
        for i in range(reader.FieldCount)
    ]
    culture = clients()[3]
    while reader.Read():
        record = {}
        for i, column in enumerate(columns):
            if reader.IsDBNull(i):
                record[column] = None
                continue
            value = reader.GetValue(i)
            if isinstance(value, (str, int, float, bool)):
                record[column] = value
                continue
            kind = value.GetType().FullName
            if kind == "System.Decimal":
                value = Decimal(value.ToString(culture))
            elif kind in ("System.DateTime", "System.DateTimeOffset"):
                value = datetime.fromisoformat(value.ToString("o", culture))
            elif kind in (
                "System.Int16",
                "System.Int32",
                "System.Int64",
                "System.Byte",
            ):
                value = int(value)
            elif kind in ("System.Double", "System.Single"):
                value = float(value)
            elif kind == "System.Boolean":
                value = bool(value)
            else:
                value = str(value)
            record[column] = value
        result.append(record)
    return result


def sql(query, parameters=None):
    SqlConnection, _, SqlDbType, _ = clients()
    connection = SqlConnection(
        "Server=lpc:localhost;Database=FxWarehouse;Integrated Security=True;Application Name=FxSettlementDashboard;Connect Timeout=10;"
    )
    command = None
    reader = None
    try:
        connection.Open()
        command = connection.CreateCommand()
        command.CommandText = query
        command.CommandTimeout = 30
        for name, value in (parameters or {}).items():
            text = str(value)
            command.Parameters.Add(
                "@" + name, SqlDbType.VarChar, max(len(text), 1)
            ).Value = text
        reader = command.ExecuteReader()
        return rows(reader)
    finally:
        if reader is not None:
            reader.Dispose()
        if command is not None:
            command.Dispose()
        connection.Dispose()


def dax(query):
    _, AdomdConnection, _, _ = clients()
    connection = AdomdConnection(
        "Data Source=localhost:2384;Initial Catalog=FxSettlement;Connect Timeout=10;"
    )
    command = None
    reader = None
    try:
        connection.Open()
        command = connection.CreateCommand()
        command.CommandText = query
        command.CommandTimeout = 30
        reader = command.ExecuteReader()
        return rows(reader)
    finally:
        if reader is not None:
            reader.Dispose()
        if command is not None:
            command.Dispose()
        connection.Dispose()
