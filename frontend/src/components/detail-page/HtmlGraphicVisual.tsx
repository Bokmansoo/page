import React from "react";
import {
  DetailPageSectionVisual,
  VisualCard,
  VisualChecklistItem,
  VisualNumericHighlight,
  VisualStep,
  VisualTableRow,
} from "./types";

interface HtmlGraphicVisualProps {
  section: DetailPageSectionVisual;
}

function CardList({
  cards,
  layoutVariant,
}: {
  cards: VisualCard[];
  layoutVariant: string;
}) {
  const isComparison = layoutVariant === "comparison_cards";
  const gridCols = isComparison ? "sm:grid-cols-2" : "sm:grid-cols-2 lg:grid-cols-3";

  return (
    <div className={`mt-8 grid gap-4 ${gridCols}`}>
      {cards.map((card, idx) => {
        const toneStyles: Record<string, string> = {
          positive:
            "border-emerald-200 bg-emerald-50 text-emerald-900",
          muted: "border-slate-200 bg-slate-50 text-slate-600",
          warning: "border-amber-200 bg-amber-50 text-amber-800",
        };
        const cardStyle =
          toneStyles[card.tone || ""] ||
          "border-slate-200 bg-white text-slate-900";

        return (
          <div
            key={idx}
            className={`min-w-0 rounded-xl border p-5 text-left shadow-sm ${cardStyle}`}
          >
            {card.icon_key ? (
              <div className="mb-2 text-2xl">{card.icon_key}</div>
            ) : null}
            <h4 className="text-sm font-extrabold">{card.title}</h4>
            <p className="mt-1 text-xs leading-relaxed opacity-80">
              {card.body}
            </p>
            <p className="mt-3 text-[11px] font-bold opacity-75">
              {card.provenance_label || "판매자 제공 정보"}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function NumericHighlights({ highlights }: { highlights: VisualNumericHighlight[] }) {
  return (
    <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="핵심 수치">
      {highlights.map((item, index) => (
        <div key={`${item.label}-${index}`} className="min-w-0 rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-left text-emerald-950 shadow-sm">
          <p className="break-words text-xs font-bold text-emerald-800">{item.label}</p>
          <p className="mt-2 break-words text-3xl font-black tracking-tight">{item.value}</p>
          {item.body ? <p className="mt-2 break-words text-xs leading-relaxed text-emerald-900/80">{item.body}</p> : null}
          <p className="mt-3 text-[11px] font-bold text-emerald-800">
            {item.provenance_label || "판매자 제공 정보"}
          </p>
        </div>
      ))}
    </div>
  );
}

function Steps({ steps }: { steps: VisualStep[] }) {
  return (
    <ol className="mt-8 grid gap-3 sm:grid-cols-2" aria-label="사용 단계">
      {steps.map((item, index) => (
        <li key={`${item.step}-${index}`} className="flex min-w-0 gap-3 rounded-xl border border-sky-100 bg-sky-50 p-4 text-left">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sky-700 text-xs font-extrabold text-white">
            {item.step}
          </span>
          <div className="min-w-0">
            <h4 className="text-sm font-extrabold text-slate-900">{item.title}</h4>
            <p className="mt-1 break-words text-xs leading-relaxed text-slate-600">{item.body}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Checklist({ items }: { items: VisualChecklistItem[] }) {
  return (
    <ul className="mt-8 grid gap-2 sm:grid-cols-2" aria-label="구매 전 확인 사항">
      {items.map((item, index) => (
        <li key={`${item.text}-${index}`} className="flex min-w-0 items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-4 py-3 text-left text-sm text-emerald-950">
          <span aria-hidden="true" className="mt-0.5 font-extrabold text-emerald-700">✓</span>
          <span className="min-w-0 break-words font-semibold">{item.text}</span>
          <span className="sr-only">{item.verification_status === "action_required" ? "판매자 확인 필요" : "확인된 상품 정보"}</span>
        </li>
      ))}
    </ul>
  );
}

function SpecTable({ rows }: { rows: VisualTableRow[] }) {
  return (
    <div className="mt-8 overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-[420px] w-full text-left text-sm">
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={idx}
              className={idx % 2 === 0 ? "bg-white" : "bg-slate-50"}
            >
              <th className="w-1/3 break-words border-r border-slate-200 px-4 py-3 font-bold text-slate-700">
                {row.label}
              </th>
              <td className="break-words px-4 py-3 text-slate-600">{row.value}</td>
              <td className="px-2 py-3 text-right text-xs font-bold text-emerald-700">
                {row.provenance_label || "판매자 제공"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function HtmlGraphicVisual({ section }: HtmlGraphicVisualProps) {
  const payload = (section.visual_payload || {}) as Record<string, unknown>;
  const layoutVariant = (payload.layout_variant as string) || "image_text";

  // DetailPageDocument already renders the title and formatted body copy.
  // Text-only/fallback layouts have no additional graphic to render; drawing
  // the body here again duplicated every paragraph in preview and export.
  if (
    payload.strategy === "text_only" ||
    layoutVariant === "image_text" ||
    layoutVariant === "hero_overlay"
  ) {
    return null;
  }

  return (
    <div data-section-visual="html_graphic">
      {layoutVariant === "comparison_cards" && payload.cards ? (
        <CardList cards={payload.cards as VisualCard[]} layoutVariant={layoutVariant} />
      ) : null}
      {layoutVariant === "benefit_cards" && payload.cards ? (
        <CardList cards={payload.cards as VisualCard[]} layoutVariant={layoutVariant} />
      ) : null}
      {layoutVariant === "spec_table" && payload.table_rows ? (
        <SpecTable rows={payload.table_rows as VisualTableRow[]} />
      ) : null}
      {layoutVariant === "numeric_highlights" && payload.highlights ? (
        <NumericHighlights highlights={payload.highlights as VisualNumericHighlight[]} />
      ) : null}
      {layoutVariant === "steps" && payload.steps ? (
        <Steps steps={payload.steps as VisualStep[]} />
      ) : null}
      {layoutVariant === "checklist" && payload.items ? (
        <Checklist items={payload.items as VisualChecklistItem[]} />
      ) : null}
    </div>
  );
}
