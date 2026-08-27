package com.ktcloud.travelplanner.auth.client

import com.ktcloud.travelplanner.user.model.OAuthProvider
import java.net.URI

data class OAuthUserProfile(
	val provider: OAuthProvider,
	val providerUserId: String,
	val email: String?,
	val name: String?,
	val profileImageUrl: String?,
)

data class OAuthAuthorizationGrant(
	val authorizationCode: String,
	val state: String,
)

interface OAuthProviderClient {
	val provider: OAuthProvider

	// forceAccountSelection=true면 구글 prompt=select_account / 네이버 auth_type=reprompt를 붙여
	// 세션이 남아있어도 계정 선택 화면을 강제한다. 기본 로그인 버튼(false)은 항상 조용히 통과시키고,
	// "다른 계정으로 로그인" 링크를 명시적으로 눌렀을 때(true)만 강제한다 — 모든 로그인에 무조건
	// 강제했던 이전 구현이 매번 계정 선택을 띄우고, 여러 계정이 로그인된 브라우저에서는 실수로
	// 다른 계정을 골라 별개의 신규 회원으로 가입되는 사고로 이어졌다.
	fun createAuthorizationUrl(
		state: String,
		forceAccountSelection: Boolean,
	): URI

	fun fetchUserProfile(grant: OAuthAuthorizationGrant): OAuthUserProfile
}
