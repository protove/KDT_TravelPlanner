import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { ConfirmDialog } from "./ConfirmDialog";

const meta = {
  title: "Molecules/ConfirmDialog",
  component: ConfirmDialog,
  tags: ["autodocs"],
} satisfies Meta<typeof ConfirmDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

function DeleteTripDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="destructive" onClick={() => setOpen(true)}>
        여행일정 삭제
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="여행일정 삭제"
        description="삭제하면 되돌릴 수 없습니다."
        confirmLabel="삭제하기"
        destructive
        onConfirm={() => {}}
      />
    </>
  );
}

function LeaveTripDemo() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        일정 나가기
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="일정을 나가시겠어요?"
        description="다시 참여하려면 초대를 받아야 해요."
        confirmLabel="나가기"
        onConfirm={() => {}}
      />
    </>
  );
}

const noopArgs = { open: false, onOpenChange: () => {}, title: "", onConfirm: () => {} };

export const Destructive: Story = { args: noopArgs, render: () => <DeleteTripDemo /> };
export const NonDestructive: Story = { args: noopArgs, render: () => <LeaveTripDemo /> };
