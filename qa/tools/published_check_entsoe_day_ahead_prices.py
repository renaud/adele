import duckdb, sys
c = duckdb.connect(); c.execute("SET TimeZone='UTC'")
c.execute(f"""CREATE VIEW p AS SELECT *, CASE WHEN bidding_zone IN ('DE_AT_LU','DE_LU') THEN 'DE' ELSE bidding_zone END AS z,
  delivery_start AT TIME ZONE 'Europe/Berlin' AS tl FROM read_parquet('{sys.argv[1]}/entsoe_day_ahead_prices/prices/*.parquet')""")
c.execute("""CREATE VIEW y AS SELECT z, year(tl) AS yr,
  round(sum(price*epoch(resolution))/sum(epoch(resolution)),2) AS mean_tw,
  round(avg(price),2) AS mean_rows,
  round(sum(epoch(resolution)) FILTER (WHERE price<0)/3600,2) AS neg_h_time,
  round(min(price),2) AS mn, round(max(price),2) AS mx, round(stddev_samp(price),2) AS sd
  FROM p GROUP BY ALL""")
c.execute("""CREATE VIEW dm AS SELECT z, yr, round(avg(d),2) AS mean_of_daily FROM
  (SELECT z, year(tl) AS yr, tl::DATE AS dday, sum(price*epoch(resolution))/sum(epoch(resolution)) AS d FROM p GROUP BY ALL) GROUP BY ALL""")
pub = [  # zone, year, statistic, published value, source
 ("DE",2015,"neg_h_time",126,"ElCom"),("DE",2016,"neg_h_time",97,"ElCom"),("DE",2017,"neg_h_time",146,"ElCom"),("DE",2018,"neg_h_time",119,"ElCom (134 BNetzA)"),
 ("DE",2019,"neg_h_time",211,"ElCom"),("DE",2020,"neg_h_time",298,"ElCom+SMARD"),("DE",2021,"neg_h_time",139,"SMARD"),("DE",2022,"neg_h_time",69,"SMARD"),
 ("DE",2023,"neg_h_time",301,"SMARD"),("DE",2024,"neg_h_time",457,"SMARD (459 FfE)"),("DE",2025,"neg_h_time",573,"SMARD (~575 FfE)"),
 ("DE",2015,"mn",-79.94,"ElCom"),("DE",2016,"mn",-130.09,"ElCom"),("DE",2017,"mn",-83.06,"ElCom"),("DE",2018,"mn",-76.01,"ElCom"),("DE",2019,"mn",-90.01,"ElCom"),
 ("DE",2020,"mn",-83.94,"ElCom+SMARD"),("DE",2021,"mn",-69.00,"SMARD"),("DE",2022,"mn",-19.04,"SMARD"),("DE",2023,"mn",-500.00,"SMARD"),("DE",2024,"mn",-135.45,"SMARD"),("DE",2025,"mn",-250.32,"SMARD"),
 ("DE",2020,"mx",200.04,"SMARD"),("DE",2021,"mx",620.00,"SMARD"),("DE",2022,"mx",871.00,"SMARD"),("DE",2023,"mx",524.27,"SMARD"),("DE",2024,"mx",936.28,"SMARD"),("DE",2025,"mx",583.40,"SMARD"),
 ("DE",2020,"mean_tw",30.47,"SMARD+ElCom"),("DE",2021,"mean_tw",96.85,"SMARD+ElCom"),("DE",2022,"mean_tw",235.45,"SMARD"),("DE",2023,"mean_tw",95.18,"SMARD"),("DE",2024,"mean_tw",78.51,"SMARD"),("DE",2025,"mean_tw",89.32,"SMARD"),
 ("CH",2015,"neg_h_time",9,"ElCom"),("CH",2016,"neg_h_time",24,"ElCom"),("CH",2017,"neg_h_time",5,"ElCom"),("CH",2018,"neg_h_time",29,"ElCom"),("CH",2019,"neg_h_time",17,"ElCom"),("CH",2020,"neg_h_time",75,"ElCom"),
 ("CH",2015,"mn",-11.66,"ElCom+Keles"),("CH",2016,"mn",-45.68,"ElCom+Keles"),("CH",2017,"mn",-49.95,"ElCom+Keles"),("CH",2018,"mn",-30.62,"ElCom+Keles"),("CH",2019,"mn",-39.45,"ElCom"),("CH",2020,"mn",-59.61,"ElCom"),
 ("CH",2015,"mean_tw",40.30,"Keles"),("CH",2016,"mean_tw",37.88,"Keles"),("CH",2017,"mean_tw",46.00,"Keles"),("CH",2018,"mean_tw",52.22,"Keles"),
 ("CH",2015,"sd",13.15,"Keles"),("CH",2016,"sd",16.80,"Keles"),("CH",2017,"sd",19.60,"Keles"),("CH",2018,"sd",16.43,"Keles"),
 ("CH",2015,"mx",114.98,"Keles"),("CH",2016,"mx",120.90,"Keles"),("CH",2017,"mx",179.92,"Keles"),("CH",2018,"mx",161.35,"Keles"),
 ("CH",2024,"mean_tw",75.96,"SMARD"),("CH",2025,"mean_tw",101.69,"SMARD"),
 ("CH",2019,"mean_of_daily",40.92,"ElCom"),("CH",2020,"mean_of_daily",34.00,"ElCom"),("CH",2021,"mean_of_daily",114.92,"ElCom"),("CH",2022,"mean_of_daily",281.66,"ElCom"),
 ("DE",2019,"mean_of_daily",37.67,"ElCom"),("FR",2019,"mean_of_daily",39.45,"ElCom"),("FR",2020,"mean_of_daily",32.20,"ElCom"),("FR",2021,"mean_of_daily",109.17,"ElCom"),("FR",2022,"mean_of_daily",275.89,"ElCom"),
 ("FR",2015,"neg_h_time",0,"ElCom"),("FR",2016,"neg_h_time",2,"ElCom"),("FR",2017,"neg_h_time",4,"ElCom"),("FR",2018,"neg_h_time",11,"ElCom"),("FR",2019,"neg_h_time",27,"ElCom"),("FR",2020,"neg_h_time",102,"ElCom"),
 ("FR",2023,"neg_h_time",147,"CRE"),("FR",2024,"neg_h_time",352,"CRE+RTE"),("FR",2025,"neg_h_time",513,"RTE"),
 ("FR",2016,"mn",-10.69,"ElCom"),("FR",2017,"mn",-2.17,"ElCom"),("FR",2018,"mn",-31.82,"ElCom"),("FR",2019,"mn",-24.92,"ElCom"),("FR",2020,"mn",-75.82,"ElCom"),
 ("FR",2023,"mean_tw",96.9,"CRE"),("FR",2024,"mean_tw",58.02,"SMARD (57.7 CRE)"),("FR",2025,"mean_tw",61.07,"SMARD"),("FR",2015,"mean_tw",38.44,"Tschora"),
]
ok = bad = 0
for z, yr, stat, val, src in pub:
    tbl = "dm" if stat == "mean_of_daily" else "y"
    got = c.execute(f"SELECT {stat} FROM {tbl} WHERE z=? AND yr=?", [z, yr]).fetchone()[0]
    tol = 0.011 if stat != "neg_h_time" else 0.5
    match = got is not None and abs(float(got) - val) <= tol
    ok += match; bad += (not match)
    if not match:
        extra = c.execute("SELECT mean_rows FROM y WHERE z=? AND yr=?", [z, yr]).fetchone()[0] if stat == "mean_tw" else ""
        print(f"DIFF {z} {yr} {stat}: published {val} ({src}), adele {got} {('rows-mean '+str(extra)) if extra != '' else ''}")
print(f"{ok} match, {bad} differ, of {len(pub)}")
print("DE_LU on 2024-06-26 (EPEX decoupling day):", c.execute("SELECT min(price), max(price), count(*) FROM p WHERE bidding_zone='DE_LU' AND tl::DATE = DATE '2024-06-26'").fetchall())
print("2025 negative hours, other definitions (hourly mean of quarters < 0; any quarter < 0):")
print(c.execute("""SELECT z, count(*) FILTER (WHERE m < 0) AS hourly_mean_neg, count(*) FILTER (WHERE mnq < 0) AS any_quarter_neg FROM
  (SELECT z, date_trunc('hour', delivery_start) h, sum(price*epoch(resolution))/sum(epoch(resolution)) m, min(price) mnq FROM p WHERE year(tl)=2025 GROUP BY ALL)
  WHERE z IN ('DE','FR') GROUP BY 1""").fetchall())
