const page = document.body.dataset.page;
const notice = document.querySelector("#notice");

function setNotice(message, type = "success") {
  if (!notice) return;
  notice.textContent = message;
  notice.classList.toggle("error", type === "error");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function typographRu(value) {
  const shortWords = "а|в|во|и|из|к|ко|на|не|но|о|об|от|по|с|со|у|за|до|для|или|над|под|при|без";
  return String(value ?? "").replace(new RegExp(`(^|[\\s(«„"])(${shortWords})\\s+`, "giu"), "$1$2\u00a0");
}

function textHtml(value) {
  return escapeHtml(typographRu(value));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw data;
  return data;
}

function rubToCents(value) {
  return Math.round(Number(value || 0) * 100);
}

function centsToRub(value) {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format((value || 0) / 100);
}

function centsToRubInput(value) {
  return Math.round(Number(value || 0) / 100);
}

function formatDate(value) {
  if (!value) return "Дата не указана";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function toDatetimeLocal(value) {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return value.slice(0, 16);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
}

function humanStatus(status) {
  const map = {
    PAYMENT_PENDING: "Ожидает оплаты",
    PAID_QR_PENDING: "Оплата получена, письмо готовится",
    READY: "Код отправлен на почту",
    EMAIL_FAILED: "Письмо не отправлено",
    USED: "Билет уже использован",
  };
  return map[status] || status || "Статус неизвестен";
}

function errorMessage(error) {
  if (error?.detail) return Array.isArray(error.detail) ? "Проверьте заполнение формы." : error.detail;
  return "Не удалось выполнить действие. Проверьте, что система запущена.";
}

function renderEvents(events, eventsList, eventSelect) {
  if (!events.length) {
    if (eventsList) eventsList.innerHTML = '<div class="empty">Пока нет мероприятий.</div>';
    if (eventSelect) eventSelect.innerHTML = '<option value="">Сначала организатор должен создать мероприятие</option>';
    return;
  }

  if (eventsList) {
    eventsList.innerHTML = events
      .map(
        (event) => {
          const total = Number(event.total_tickets || 0);
          const available = Number(event.available_tickets || 0);
          const ratio = total > 0 ? available / total : 0;
          const statusClass = ratio <= 0.2 ? "is-low" : ratio <= 0.5 ? "is-medium" : "is-high";
          return `
          <article class="event-card">
            <div class="event-copy">
              <h3>${textHtml(event.title)}</h3>
              <p>${textHtml(event.description || "Описание появится позже")}</p>
              <p>${textHtml(event.location)}</p>
            </div>
            <div class="event-meta">
              <div class="event-facts">
                <span class="meta-date">${textHtml(formatDate(event.event_date))}</span>
                <strong>${centsToRub(event.price_cents)}</strong>
              </div>
              <span class="pill ${statusClass}">${available} / ${total} билетов</span>
            </div>
          </article>
        `;
        },
      )
      .join("");
  }

  if (eventSelect) {
    eventSelect.innerHTML = events
      .map((event) => `<option value="${event.id}">${textHtml(event.title)} — ${centsToRub(event.price_cents)}</option>`)
      .join("");
  }
}

async function loadEvents(eventsList, eventSelect) {
  const events = await api("/events");
  renderEvents(events, eventsList, eventSelect);
  return events;
}

function eventFormPayload(form) {
  return {
    title: form.get("title"),
    description: form.get("description"),
    event_date: form.get("event_date"),
    location: form.get("location"),
    total_tickets: Number(form.get("total_tickets")),
    price_cents: rubToCents(form.get("price_rub")),
  };
}

function renderManagedEvents(events, manageEventsList) {
  if (!manageEventsList) return;
  if (!events.length) {
    manageEventsList.innerHTML = '<div class="empty">Пока нет мероприятий для управления.</div>';
    return;
  }

  manageEventsList.innerHTML = events
    .map(
      (event) => `
        <article class="manage-event" data-event-id="${event.id}">
          <div class="manage-event-copy">
            <h3>${textHtml(event.title)}</h3>
            <p>${textHtml(formatDate(event.event_date))} · ${textHtml(event.location)}</p>
          </div>
          <div class="manage-event-actions">
            <button class="secondary-action" type="button" data-action="edit">Редактировать</button>
            <button class="danger-action" type="button" data-action="delete">Удалить</button>
          </div>
        </article>
      `,
    )
    .join("");
}

function initVisitor() {
  const eventsList = document.querySelector("#eventsList");
  const eventSelect = document.querySelector("#eventSelect");
  const paymentBox = document.querySelector("#paymentBox");
  const paymentClose = document.querySelector("#paymentClose");
  const paymentQr = document.querySelector("#paymentQr");
  const paymentLink = document.querySelector("#paymentLink");

  loadEvents(eventsList, eventSelect).catch((error) => setNotice(errorMessage(error), "error"));

  function closePaymentModal() {
    paymentBox.classList.add("hidden");
  }

  paymentClose.addEventListener("click", closePaymentModal);
  paymentBox.addEventListener("click", (event) => {
    if (event.target === paymentBox) closePaymentModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !paymentBox.classList.contains("hidden")) closePaymentModal();
  });

  document.querySelector("#ticketForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      event_id: Number(form.get("event_id")),
      buyer_name: form.get("buyer_name"),
      buyer_email: form.get("buyer_email"),
    };

    try {
      const ticket = await api("/tickets", { method: "POST", body: JSON.stringify(payload) });
      paymentQr.src = ticket.payment_qr_url;
      paymentLink.href = ticket.payment_url;
      paymentBox.classList.remove("hidden");
      paymentClose.focus();
      setNotice("Билет зарезервирован. Отсканируйте QR-код оплаты или откройте страницу оплаты.");
      await loadEvents(eventsList, eventSelect);
    } catch (error) {
      setNotice(errorMessage(error), "error");
    }
  });
}

function initOrganizer() {
  const eventForm = document.querySelector("#eventForm");
  const manageEventsList = document.querySelector("#manageEventsList");
  const cancelEdit = document.querySelector("#cancelEdit");
  let organizerEvents = [];

  async function refreshOrganizerEvents() {
    organizerEvents = await loadEvents(null, null);
    renderManagedEvents(organizerEvents, manageEventsList);
  }

  function resetEventForm() {
    eventForm.reset();
    eventForm.elements.event_id.value = "";
    eventForm.querySelector('button[type="submit"]').textContent = "Создать мероприятие";
    cancelEdit.classList.add("hidden");
  }

  eventForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const eventId = form.get("event_id");
    const payload = eventFormPayload(form);

    try {
      const saved = eventId
        ? await api(`/events/${eventId}`, { method: "PUT", body: JSON.stringify(payload) })
        : await api("/events", { method: "POST", body: JSON.stringify(payload) });
      setNotice(eventId ? `Мероприятие "${saved.title}" обновлено.` : `Мероприятие "${saved.title}" создано.`);
      resetEventForm();
      await refreshOrganizerEvents();
    } catch (error) {
      setNotice(errorMessage(error), "error");
    }
  });

  cancelEdit.addEventListener("click", resetEventForm);

  manageEventsList.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const row = button.closest(".manage-event");
    const eventId = Number(row.dataset.eventId);
    const selectedEvent = organizerEvents.find((item) => item.id === eventId);
    if (!selectedEvent) return;

    if (button.dataset.action === "edit") {
      eventForm.elements.event_id.value = selectedEvent.id;
      eventForm.elements.title.value = selectedEvent.title;
      eventForm.elements.description.value = selectedEvent.description || "";
      eventForm.elements.event_date.value = toDatetimeLocal(selectedEvent.event_date);
      eventForm.elements.location.value = selectedEvent.location;
      eventForm.elements.total_tickets.value = selectedEvent.total_tickets;
      eventForm.elements.price_rub.value = centsToRubInput(selectedEvent.price_cents);
      eventForm.querySelector('button[type="submit"]').textContent = "Сохранить изменения";
      cancelEdit.classList.remove("hidden");
      eventForm.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    if (!window.confirm(`Удалить мероприятие "${selectedEvent.title}"?`)) return;

    try {
      await api(`/events/${eventId}`, { method: "DELETE" });
      setNotice(`Мероприятие "${selectedEvent.title}" удалено.`);
      if (eventForm.elements.event_id.value === String(eventId)) resetEventForm();
      await refreshOrganizerEvents();
    } catch (error) {
      setNotice(errorMessage(error), "error");
    }
  });

  refreshOrganizerEvents().catch((error) => setNotice(errorMessage(error), "error"));

  document.querySelector("#validateForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const qrToken = new FormData(event.currentTarget).get("qr_token");

    try {
      const result = await api("/tickets/validate", {
        method: "POST",
        body: JSON.stringify({ qr_token: qrToken }),
      });
      setNotice(result.ok ? "Проход разрешён. Гость отмечен." : result.message, result.ok ? "success" : "error");
    } catch (error) {
      setNotice(errorMessage(error), "error");
    }
  });
}

function paymentTicketId() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[1];
}

function renderPaymentDetails(ticket, event) {
  document.querySelector("#paymentTitle").textContent = event.title;
  document.querySelector("#paymentDetails").innerHTML = `
    <div>
      <dt>Дата</dt>
      <dd>${escapeHtml(formatDate(event.event_date))}</dd>
    </div>
    <div>
      <dt>Место</dt>
      <dd>${escapeHtml(event.location)}</dd>
    </div>
    <div>
      <dt>Гость</dt>
      <dd>${escapeHtml(ticket.buyer_name)}</dd>
    </div>
    <div>
      <dt>Email</dt>
      <dd>${escapeHtml(ticket.buyer_email)}</dd>
    </div>
    <div>
      <dt>К оплате</dt>
      <dd>${centsToRub(event.price_cents)}</dd>
    </div>
    <div>
      <dt>Статус</dt>
      <dd>${escapeHtml(humanStatus(ticket.status))}</dd>
    </div>
  `;
}

async function initPayment() {
  const ticketId = paymentTicketId();
  const payButton = document.querySelector("#payButton");

  try {
    const ticket = await api(`/tickets/${ticketId}`);
    const event = await api(`/events/${ticket.event_id}`);
    renderPaymentDetails(ticket, event);
    setNotice("Проверьте данные и нажмите “Оплатить”.");

    if (ticket.status !== "PAYMENT_PENDING") {
      payButton.disabled = true;
      payButton.textContent = humanStatus(ticket.status);
    }
  } catch (error) {
    setNotice(errorMessage(error), "error");
    payButton.disabled = true;
  }

  payButton.addEventListener("click", async () => {
    try {
      const ticket = await api(`/tickets/${ticketId}/pay`, { method: "POST" });
      const event = await api(`/events/${ticket.event_id}`);
      renderPaymentDetails(ticket, event);
      payButton.disabled = true;
      payButton.textContent = "Оплата принята";
      setNotice("Оплата прошла. Код билета будет отправлен на указанную почту.");
    } catch (error) {
      setNotice(errorMessage(error), "error");
    }
  });
}

if (page === "visitor") initVisitor();
if (page === "organizer") initOrganizer();
if (page === "payment") initPayment();