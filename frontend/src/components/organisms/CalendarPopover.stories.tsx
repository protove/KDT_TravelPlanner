import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CalendarPopover, type DateRange } from "./CalendarPopover";

const meta = {
  title: "Organisms/CalendarPopover",
  component: CalendarPopover,
  tags: ["autodocs"],
} satisfies Meta<typeof CalendarPopover>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [range, setRange] = React.useState<DateRange>({
    start: new Date(2027, 3, 2),
    end: new Date(2027, 3, 5),
  });

  return <CalendarPopover value={range} onChange={setRange} onApply={() => {}} />;
}

export const Default: Story = {
  args: { value: { start: new Date(2027, 3, 2), end: new Date(2027, 3, 5) }, onChange: () => {}, onApply: () => {} },
  render: () => <Demo />,
};
