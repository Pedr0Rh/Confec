// ==========================================
// CONTROLE DE ALERTAS PERSISTENTES
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    // Alertas que NUNCA fecham automaticamente (até o usuário clicar)
    const alertasPersistentes = document.querySelectorAll('.alert-persistent, .alert-warning, .alert-danger');
    alertasPersistentes.forEach(function(alert) {
        alert.dataset.autoClose = 'false';
    });

    // Alertas que fecham após 20 segundos
    const alertasDemorados = document.querySelectorAll('.alert-success, .alert-info');
    alertasDemorados.forEach(function(alert) {
        if (alert.dataset.autoClose !== 'false') {
            setTimeout(function() {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
                if (bsAlert) bsAlert.close();
            }, 20000);
        }
    });

    // Alertas que fecham após 10 segundos (os mais leves)
    const alertasRapidos = document.querySelectorAll('.alert-primary, .alert-secondary');
    alertasRapidos.forEach(function(alert) {
        if (alert.dataset.autoClose !== 'false') {
            setTimeout(function() {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
                if (bsAlert) bsAlert.close();
            }, 10000);
        }
    });
});

// ===== FUNÇÃO PARA FECHAR ALERTA MANUALMENTE =====
function fecharAlerta(element) {
    const alert = element.closest('.alert');
    if (alert) {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
        if (bsAlert) bsAlert.close();
    }
}

// ===== FUNÇÃO PARA CRIAR ALERTA PERSISTENTE =====
function criarAlertaPersistente(mensagem, tipo = 'warning') {
    const alertaDiv = document.createElement('div');
    alertaDiv.className = `alert alert-${tipo} alert-dismissible fade show alert-persistent`;
    alertaDiv.role = 'alert';
    alertaDiv.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="bi ${tipo === 'success' ? 'bi-check-circle-fill' : tipo === 'danger' ? 'bi-x-circle-fill' : 'bi-info-circle-fill'} fs-2 me-3"></i>
            <div>
                <strong>${mensagem}</strong>
            </div>
            <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    const container = document.querySelector('.main-content');
    if (container) {
        container.insertBefore(alertaDiv, container.firstChild);
    }
    
    return alertaDiv;
}