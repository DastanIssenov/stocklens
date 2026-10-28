"""Phase 0 probe: yfinance coverage for US backup + Kazakh stocks listed abroad + FX/oil."""
import yfinance as yf
cands = ["AAPL", "KSPI", "FRHC", "KAP.IL", "KAP.L", "HSBK.IL", "HSBK.L", "AIRA.IL", "AIRA.L", "KCEL.IL",
         "CAML.L", "CASP.L", "KZT=X", "USDKZT=X", "BZ=F", "^GSPC", "^NDX", "KZAP.KZ", "HSBK.KZ"]
for t in cands:
    try:
        h = yf.Ticker(t).history(period="max", interval="1d", auto_adjust=False)
        if h.empty:
            print(f"{t:10s} EMPTY"); continue
        last = h.iloc[-1]
        print(f"{t:10s} rows={len(h):5d} first={h.index[0].date()} last={h.index[-1].date()} close={last['Close']:.2f} vol={int(last['Volume'])} cur={yf.Ticker(t).fast_info.get('currency')}")
    except Exception as e:
        print(f"{t:10s} ERROR {type(e).__name__}: {str(e)[:100]}")
