# SPX Live Calendar Scanner v1.3

Fixes gegenüber v1.2:
- nutzt `reqSecDefOptParams()` und zeigt die gefundenen IBKR-Chains nach TradingClass/Exchange an
- lädt SPX und SPXW Expirations robuster
- Market-Data-Typ wählbar: Live, Frozen, Delayed, Delayed Frozen
- längere Wartezeit möglich
- zeigt Diagnose, warum Greeks fehlen können

Start:
```bash
pip install -r requirements.txt
streamlit run app.py
```

TWS/IB Gateway:
- API aktivieren
- Paper meist Port 7497, Live meist 7496
- SPX-Optionsdaten benötigen passende Marktdatenfreigabe; ohne Live-Abo Delayed/Delayed Frozen testen.
