package com.ktcloud.travelplanner.travel.model

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import jakarta.persistence.UniqueConstraint
import java.util.UUID

// Travel과 독립된 Entity로 분리 — Travel.version(낙관적 락) 계산에 영향을 주지 않기 위함
@Entity
@Table(
        name = "planner_purposes",
        uniqueConstraints = [UniqueConstraint(columnNames = ["planner_id", "purpose"])],
)
class PlannerPurpose(
        @Id
        val id: UUID = UUID.randomUUID(),

        @ManyToOne(fetch = FetchType.LAZY, optional = false)
        @JoinColumn(name = "planner_id", nullable = false)
        val travel: Travel,

        @Enumerated(EnumType.STRING)
        @Column(name = "purpose", nullable = false, length = 30)
        val purpose: TravelPurpose,
)
