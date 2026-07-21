import { NextResponse, type NextRequest } from "next/server";

const PROTECTED = ["/trips", "/mypage", "/notifications", "/community"];
const GUEST_ONLY = ["/auth", "/landing"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const loggedIn = request.cookies.get("logged_in")?.value === "1";

  if (pathname === "/") {
    return NextResponse.redirect(
      new URL(loggedIn ? "/trips" : "/landing", request.url),
    );
  }

  if (!loggedIn && PROTECTED.some((p) => pathname.startsWith(p))) {
    const url = new URL("/auth", request.url);
    url.searchParams.set("redirect", pathname);
    return NextResponse.redirect(url);
  }

  if (loggedIn && GUEST_ONLY.some((p) => pathname.startsWith(p))) {
    return NextResponse.redirect(new URL("/trips", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/auth",
    "/landing",
    "/trips/:path*",
    "/mypage/:path*",
    "/notifications/:path*",
    "/community/:path*",
  ],
};
