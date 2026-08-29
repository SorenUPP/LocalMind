import duckdb

con = duckdb.connect("data/localmind.duckdb")
con.execute("CREATE OR REPLACE TABLE sales AS SELECT * FROM read_csv_auto('data/sales.csv')")
print("Sales data loaded.")
