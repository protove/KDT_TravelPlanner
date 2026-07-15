package com.ktcloud.travelplanner.global.response

import org.springframework.data.domain.Page

data class PageResponse<T>(
	val content: List<T>,
	val page: Int,
	val size: Int,
	val totalElements: Long,
	val totalPages: Int,
	val isFirst: Boolean,
	val isLast: Boolean,
) {
	companion object {
		fun <T> from(page: Page<T>): PageResponse<T> = PageResponse(
			content = page.content,
			page = page.number,
			size = page.size,
			totalElements = page.totalElements,
			totalPages = page.totalPages,
			isFirst = page.isFirst,
			isLast = page.isLast,
		)
	}
}
