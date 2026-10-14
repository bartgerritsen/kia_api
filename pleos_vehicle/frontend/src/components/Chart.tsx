import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";

export interface Series {
  key: string;
  label: string;
  color: string;
}

interface Props {
  title: string;
  subtitle?: string;
  data: Record<string, number | string | null>[];
  series: Series[];
  unit?: string;
  xKey?: string;
  xFormat: (x: number) => string;
  yFormat?: (y: number) => string;
  yTicks?: number[];
  yDomain?: [number | "auto", number | "auto"];
  step?: boolean;
  height?: number;
}

export const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** One-axis line chart: 2px lines, hairline grid, crosshair tooltip, legend for 2+ series. */
export function TimeChart({
  title,
  subtitle,
  data,
  series,
  unit = "",
  xKey = "x",
  xFormat,
  yFormat,
  yTicks,
  yDomain,
  step,
  height = 220,
}: Props) {
  const fmtY = yFormat ?? ((y: number) => `${y}`);

  const renderTooltip = ({ active, payload, label }: TooltipProps<number, string>) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="tooltip">
        <div className="t">{xFormat(Number(label))}</div>
        {payload.map((p) => (
          <div className="r" key={p.dataKey as string}>
            <i style={{ background: p.color }} />
            <span>{series.find((s) => s.key === p.dataKey)?.label}</span>
            <b>
              {p.value === null || p.value === undefined ? "–" : fmtY(Number(p.value))}
              {unit && ` ${unit}`}
            </b>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="card">
      <div className="chart-title">
        <h3>{title}</h3>
        {(unit || subtitle) && <span className="muted small">{[unit, subtitle].filter(Boolean).join(" · ")}</span>}
      </div>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span key={s.key} style={{ ["--c" as string]: s.color }}>
              {s.label}
            </span>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis
            dataKey={xKey}
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={xFormat}
            stroke="var(--axis)"
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            width={52}
            stroke="var(--axis)"
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(y) => fmtY(y)}
            ticks={yTicks}
            domain={yDomain ?? ["auto", "auto"]}
            allowDecimals
          />
          <Tooltip content={renderTooltip} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} isAnimationActive={false} />
          {series.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              type={step ? "stepAfter" : "monotone"}
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
