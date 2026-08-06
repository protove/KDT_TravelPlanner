"use client";

import * as React from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/atoms/Badge";
import { Icon } from "@/components/atoms/Icon";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/atoms/Dialog";
import { UserChip } from "@/components/molecules/UserChip";
import { PermissionSelect, type Permission } from "@/components/molecules/PermissionSelect";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";

export interface Participant {
  id: string;
  name: string;
  avatarColor?: string;
  permission: Permission;
  status: "pending" | "accepted";
}

export interface ParticipantManageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  participants: Participant[];
  onPermissionChange: (id: string, permission: Permission) => void;
  onRemove: (id: string) => void;
}

function ParticipantManageDialog({
  open,
  onOpenChange,
  participants,
  onPermissionChange,
  onRemove,
}: ParticipantManageDialogProps) {
  const [removeTarget, setRemoveTarget] = React.useState<Participant | null>(null);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>참여자 관리</DialogTitle>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            {participants.map((participant) => (
              <div key={participant.id} className="flex items-center gap-2.5 rounded-xl bg-card p-2.5 shadow-card">
                <UserChip name={participant.name} avatarColor={participant.avatarColor} className="flex-1" />
                {participant.status === "pending" ? (
                  <Badge variant="secondary">대기</Badge>
                ) : (
                  <PermissionSelect
                    value={participant.permission}
                    onChange={(value) => onPermissionChange(participant.id, value)}
                  />
                )}
                <button
                  type="button"
                  title="내보내기"
                  onClick={() => setRemoveTarget(participant)}
                  className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                >
                  <Icon icon={X} size="sm" aria-label="내보내기" />
                </button>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removeTarget != null}
        onOpenChange={(next) => !next && setRemoveTarget(null)}
        title={`${removeTarget?.name ?? ""}님을 내보낼까요?`}
        description="내보내면 다시 초대해야 참여할 수 있어요."
        confirmLabel="내보내기"
        destructive
        onConfirm={() => {
          if (removeTarget) onRemove(removeTarget.id);
        }}
      />
    </>
  );
}

export { ParticipantManageDialog };
