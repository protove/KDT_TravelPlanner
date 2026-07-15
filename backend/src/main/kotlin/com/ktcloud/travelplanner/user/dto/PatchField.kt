package com.ktcloud.travelplanner.user.dto

import com.fasterxml.jackson.core.JsonParser
import com.fasterxml.jackson.databind.BeanProperty
import com.fasterxml.jackson.databind.DeserializationContext
import com.fasterxml.jackson.databind.JavaType
import com.fasterxml.jackson.databind.JsonDeserializer
import com.fasterxml.jackson.databind.annotation.JsonDeserialize
import com.fasterxml.jackson.databind.deser.ContextualDeserializer

@JsonDeserialize(using = PatchFieldDeserializer::class)
sealed interface PatchField<out T> {
	data object Absent : PatchField<Nothing>

	data class Present<T>(
		val value: T?,
	) : PatchField<T>
}

class PatchFieldDeserializer(
	private val valueType: JavaType? = null,
) : JsonDeserializer<PatchField<*>>(), ContextualDeserializer {
	override fun deserialize(
		parser: JsonParser,
		context: DeserializationContext,
	): PatchField<*> = PatchField.Present(
		context.readValue<Any?>(parser, requireNotNull(valueType)),
	)

	override fun getNullValue(context: DeserializationContext): PatchField<*> =
		PatchField.Present<Any?>(null)

	override fun createContextual(
		context: DeserializationContext,
		property: BeanProperty?,
	): JsonDeserializer<*> {
		val patchFieldType = property?.type ?: requireNotNull(context.contextualType)
		return PatchFieldDeserializer(patchFieldType.containedTypeOrUnknown(0))
	}
}
