"use client";

import { useQuery } from "@tanstack/react-query";

import { DemoBadge, Disclaimer } from "@/components/Disclaimer";
import { Card, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/app-context";

const SECTIONS: { title: Record<string, string>; body: Record<string, string> }[] = [
  {
    title: { en: "Status: demo", ru: "Статус: демо", kk: "Мәртебесі: демо" },
    body: {
      en: "The models are not trained yet. Every prediction on this site is a deterministic placeholder produced from the ticker, the date and recent price momentum, so the interface can be built and tested. They carry no information about the future.",
      ru: "Модели ещё не обучены. Все прогнозы на сайте — детерминированные заглушки, построенные из тикера, даты и недавнего моментума цены, чтобы можно было разработать и протестировать интерфейс. Никакой информации о будущем они не несут.",
      kk: "Модельдер әлі оқытылмаған. Сайттағы барлық болжамдар — тикерден, күннен және бағаның соңғы қозғалысынан құрылған детерминистік толтырғыштар. Олар болашақ туралы ешқандай ақпарат бермейді.",
    },
  },
  {
    title: {
      en: "Short term (1–5 trading days)",
      ru: "Краткосрочные (1–5 торговых дней)",
      kk: "Қысқа мерзімді (1–5 сауда күні)",
    },
    body: {
      en: "Planned: gradient-boosted trees (LightGBM and XGBoost) on technical, market, macro (rates, VIX, USD/KZT, Brent), fundamental and news-sentiment features. Targets: next-days return and direction. Validation: walk-forward with purging and embargo, compared against naive baselines.",
      ru: "План: градиентный бустинг (LightGBM и XGBoost) на технических, рыночных, макро- (ставки, VIX, USD/KZT, Brent), фундаментальных признаках и тональности новостей. Цели: доходность и направление на ближайшие дни. Проверка: walk-forward с purging и embargo, сравнение с простыми бейзлайнами.",
      kk: "Жоспар: техникалық, нарықтық, макро (мөлшерлемелер, VIX, USD/KZT, Brent), іргелі белгілер мен жаңалықтар тональдігі бойынша LightGBM және XGBoost. Мақсат: жақын күндердегі табыс пен бағыт. Тексеру: purging және embargo бар walk-forward.",
    },
  },
  {
    title: { en: "Long term (1–12 months)", ru: "Долгосрочные (1–12 месяцев)", kk: "Ұзақ мерзімді (1–12 ай)" },
    body: {
      en: "Planned: ranking models (LightGBM LambdaRank / XGBoost rank) that order stocks by expected return with monthly rebalancing. Kazakhstan gets its own settings because KASE shares trade thinly.",
      ru: "План: ранжирующие модели (LightGBM LambdaRank / XGBoost rank), упорядочивающие акции по ожидаемой доходности с ежемесячной ребалансировкой. Для Казахстана — отдельные настройки из-за низкой ликвидности KASE.",
      kk: "Жоспар: акцияларды күтілетін табыс бойынша реттейтін рейтинг модельдері (LightGBM LambdaRank / XGBoost rank), ай сайынғы ребаланспен. KASE өтімділігі төмен болғандықтан Қазақстанға бөлек баптаулар.",
    },
  },
  {
    title: { en: "News and the AI reviewer", ru: "Новости и AI-ревьюер", kk: "Жаңалықтар және AI-талдаушы" },
    body: {
      en: "A multilingual LLM (EN/RU/KZ) will read news, score sentiment per ticker and write weekly summaries. The trade reviewer comments on every paper trade with a strict JSON verdict. Right now a transparent rule-based reviewer checks concentration, volatility, recent price moves and liquidity.",
      ru: "Многоязычная LLM (EN/RU/KZ) будет читать новости, оценивать тональность по каждой бумаге и писать еженедельные сводки. Ревьюер комментирует каждую учебную сделку строгим JSON-вердиктом. Сейчас работает прозрачный rule-based ревьюер: концентрация, волатильность, недавнее движение цены, ликвидность.",
      kk: "Көптілді LLM (EN/RU/KZ) жаңалықтарды оқып, әр қағаз бойынша тональдікті бағалайды. Талдаушы әр оқу мәмілесіне қатаң JSON-шешіммен түсініктеме береді. Қазір ережелерге негізделген талдаушы жұмыс істейді: шоғырлану, құбылмалылық, бағаның соңғы қозғалысы, өтімділік.",
    },
  },
  {
    title: { en: "Ensemble and evaluation", ru: "Ансамбль и оценка", kk: "Ансамбль және бағалау" },
    body: {
      en: "Out-of-fold predictions of the tree models and the LLM sentiment are stacked. Results will be reported with AUC, RMSE, information coefficient, Sharpe, Sortino, max drawdown, turnover and hit rate — after fees and slippage, against buy-and-hold and the index.",
      ru: "Out-of-fold прогнозы деревьев и тональность от LLM объединяются стекингом. Результаты будут показаны через AUC, RMSE, IC, Sharpe, Sortino, максимальную просадку, оборот и долю попаданий — с учётом комиссий и проскальзывания, против buy-and-hold и индекса.",
      kk: "Ағаш модельдерінің out-of-fold болжамдары мен LLM тональдігі стекингпен біріктіріледі. Нәтижелер AUC, RMSE, IC, Sharpe, Sortino, максималды құлдырау, айналым көрсеткіштерімен — комиссия мен сырғуды ескере отырып беріледі.",
    },
  },
];

export function ModelsView() {
  const { t, locale } = useApp();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  return (
    <div className="space-y-4">
      <PageTitle right={<DemoBadge show={meta.data?.predictions_are_demo ?? true} />}>{t("models_title")}</PageTitle>
      <Disclaimer />
      {meta.data && (
        <p className="text-xs text-neutral-500">
          Prediction provider: <span className="font-mono">{meta.data.prediction_provider}</span> · Trade reviewer:{" "}
          <span className="font-mono">
            {meta.data.trade_reviewer} ({meta.data.trade_reviewer_model})
          </span>
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <Card key={s.title.en} title={s.title[locale] ?? s.title.en}>
            <p className="text-sm leading-relaxed text-neutral-700 dark:text-neutral-300">
              {s.body[locale] ?? s.body.en}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
