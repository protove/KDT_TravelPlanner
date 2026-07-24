import type { Permission } from "@/components/molecules/PermissionSelect";

/** 백엔드 TravelRole.kt와 대응. 초대 생성/멤버 역할 변경에 쓰인다. */
export type TravelRole = "READ_ONLY" | "READ_WRITE";

/** 백엔드 TravelPermission.kt와 대응. 여행 상세/멤버 목록 조회에 쓰인다. */
export type TravelPermission = TravelRole | "OWNER";

/** 프론트 PermissionSelect의 "read"/"write"는 owner 개념이 없어 OWNER는 별도로 분기해야 한다. */
export function toPermission(role: TravelRole): Permission {
  return role === "READ_WRITE" ? "write" : "read";
}

export function toTravelRole(permission: Permission): TravelRole {
  return permission === "write" ? "READ_WRITE" : "READ_ONLY";
}
