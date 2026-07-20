import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommentInput } from "./CommentInput";

const meta = {
  title: "Molecules/CommentInput",
  component: CommentInput,
  tags: ["autodocs"],
  decorators: [(Story) => <div className="w-[320px]"><Story /></div>],
} satisfies Meta<typeof CommentInput>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [value, setValue] = React.useState("");
  return <CommentInput value={value} onChange={setValue} onSubmit={() => setValue("")} />;
}

export const Default: Story = {
  args: { value: "", onChange: () => {}, onSubmit: () => {} },
  render: () => <Demo />,
};
