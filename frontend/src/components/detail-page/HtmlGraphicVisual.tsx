import React from "react";
import { DetailPageSectionVisual, VisualCard, VisualTableRow } from "./types";

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
  const gridCols = isComparison ? "md:grid-cols-2" : "md:grid-cols-3";

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
            className={`rounded-lg border p-5 text-left ${cardStyle}`}
          >
            {card.icon_key ? (
              <div className="mb-2 text-2xl">{card.icon_key}</div>
            ) : null}
            <h4 className="text-sm font-extrabold">{card.title}</h4>
            <p className="mt-1 text-xs leading-relaxed opacity-80">
              {card.body}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function SpecTable({ rows }: { rows: VisualTableRow[] }) {
  return (
    <div className="mt-8 overflow-hidden rounded-lg border border-slate-200">
      <table className="w-full text-left text-sm">
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={idx}
              className={idx % 2 === 0 ? "bg-white" : "bg-slate-50"}
            >
              <th className="w-1/3 border-r border-slate-200 px-4 py-3 font-bold text-slate-700">
                {row.label}
              </th>
              <td className="px-4 py-3 text-slate-600">{row.value}</td>
              {row.verification_status === "needs_review" ? (
                <td className="px-2 py-3 text-right text-xs text-amber-600">
                  검토 필요
                </td>
              ) : null}
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
      {layoutVariant === "hero_overlay" || layoutVariant === "image_text" || layoutVariant === "text_only" || (!payload.cards && !payload.table_rows) ? (
        <div className="mt-8 text-sm text-slate-500">
          <p>{section.body_copy || section.body || ""}</p>
        </div>
      ) : null}
    </div>
  );
}
