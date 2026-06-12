import Foundation
import UserNotifications

final class NotificationManager {
    static let shared = NotificationManager()

    private init() {}

    func requestAuthorization() async {
        let center = UNUserNotificationCenter.current()
        _ = try? await center.requestAuthorization(options: [.alert, .badge, .sound])
    }

    /// Schedules (or reschedules) the reminder for a commitment's next due date.
    /// Fires at 09:00 local time, `leadDays` before the due date. If that moment
    /// has already passed, falls back to 09:00 on the due date itself.
    func scheduleReminder(for commitment: Commitment, leadDays: Int) {
        cancelReminder(for: commitment)
        guard commitment.reminderEnabled, !commitment.isCompleted else { return }

        let calendar = Calendar.current
        var fireDay = calendar.date(byAdding: .day, value: -leadDays, to: commitment.nextDueDate) ?? commitment.nextDueDate
        if at9AM(fireDay) <= .now {
            fireDay = commitment.nextDueDate
        }
        guard at9AM(fireDay) > .now else { return }

        var components = calendar.dateComponents([.year, .month, .day], from: fireDay)
        components.hour = 9

        let content = UNMutableNotificationContent()
        content.title = String(localized: "notification.title")
        content.body = String(
            format: NSLocalizedString("notification.body", comment: ""),
            commitment.name,
            commitment.amount.sarFormatted
        )
        content.sound = .default

        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        let request = UNNotificationRequest(
            identifier: commitment.id.uuidString,
            content: content,
            trigger: trigger
        )
        UNUserNotificationCenter.current().add(request)
    }

    func cancelReminder(for commitment: Commitment) {
        UNUserNotificationCenter.current()
            .removePendingNotificationRequests(withIdentifiers: [commitment.id.uuidString])
    }

    func rescheduleAll(_ commitments: [Commitment], leadDays: Int) {
        for commitment in commitments {
            scheduleReminder(for: commitment, leadDays: leadDays)
        }
    }

    private func at9AM(_ date: Date) -> Date {
        Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: date) ?? date
    }
}
