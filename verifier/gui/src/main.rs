// SPDX-License-Identifier: 0BSD
//! Desktop GUI for the independent verifier (§8, §9, §14, `docs/manuel/verifier.md`).
//!
//! Presentation only: `polls-verifier-core::report::verify` does the actual
//! parsing, recomputation and comparison, shared byte-for-byte with the CLI in
//! `../cli`. This binary never touches a database and reads only the file the
//! person picks.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;

use eframe::egui;
use polls_verifier_core::report::{self, Expected, Report, VerifyError};

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([720.0, 640.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Vérificateur indépendant",
        options,
        Box::new(|cc| Ok(Box::new(VerifierApp::new(cc)))),
    )
}

#[derive(Default)]
struct VerifierApp {
    csv_path: Option<PathBuf>,
    file_error: Option<String>,
    expected_closure_hash: String,
    expected_opening_seed: String,
    expected_winner: String,
    outcome: Option<Outcome>,
}

enum Outcome {
    Report(Report),
    Error(String),
}

impl VerifierApp {
    fn new(_cc: &eframe::CreationContext<'_>) -> Self {
        Self::default()
    }

    fn choose_file(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .set_title("Choisir le fichier CSV des bulletins")
            .add_filter("CSV", &["csv"])
            .pick_file()
        {
            self.load(path);
        }
    }

    fn load(&mut self, path: PathBuf) {
        self.file_error = match std::fs::metadata(&path) {
            Ok(_) => None,
            Err(err) => Some(format!("Impossible de lire ce fichier : {err}")),
        };
        self.csv_path = Some(path);
        self.outcome = None;
    }

    fn run_verification(&mut self) {
        let Some(path) = &self.csv_path else { return };
        let text = match std::fs::read_to_string(path) {
            Ok(text) => text,
            Err(err) => {
                self.outcome = Some(Outcome::Error(format!("Impossible de lire ce fichier : {err}")));
                return;
            }
        };

        let closure_hash = non_empty(&self.expected_closure_hash);
        let opening_seed = non_empty(&self.expected_opening_seed);
        let winner = non_empty(&self.expected_winner);
        let expected = Expected { closure_hash, opening_seed, winner };

        self.outcome = Some(match report::verify(&text, &expected) {
            Ok(report) => Outcome::Report(report),
            Err(VerifyError::Csv(err)) => {
                Outcome::Error(format!("Le fichier CSV n'a pas pu être lu : {err}"))
            }
            Err(VerifyError::OpeningSeedNotHex) => Outcome::Error(
                "La graine d'ouverture doit être une suite hexadécimale (par exemple a1b2c3…)."
                    .to_string(),
            ),
        });
    }
}

fn non_empty(text: &str) -> Option<&str> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

impl eframe::App for VerifierApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        // Drag-and-drop, in addition to the browse button: egui reports files
        // dropped anywhere on the window through the raw input, no dialog
        // needed.
        let dropped: Vec<PathBuf> = ctx.input(|i| {
            i.raw.dropped_files.iter().filter_map(|f| f.path.clone()).collect()
        });
        if let Some(path) = dropped.into_iter().next() {
            self.load(path);
        }

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Vérificateur indépendant");
            ui.label(
                "Recalcule l'empreinte de clôture et le vainqueur Schulze à partir du seul \
                 fichier CSV publié, sans faire confiance ni au site, ni à la mairie \
                 (docs/manuel/verifier.md).",
            );
            ui.add_space(12.0);

            ui.group(|ui| {
                ui.label("1. Fichier CSV des bulletins");
                ui.horizontal(|ui| {
                    if ui.button("Choisir un fichier…").clicked() {
                        self.choose_file();
                    }
                    match &self.csv_path {
                        Some(path) => {
                            ui.monospace(path.display().to_string());
                        }
                        None => {
                            ui.weak("aucun fichier choisi — ou déposez-le ici");
                        }
                    }
                });
                if let Some(err) = &self.file_error {
                    ui.colored_label(egui::Color32::from_rgb(200, 40, 40), err);
                }
            });

            ui.add_space(8.0);

            ui.group(|ui| {
                ui.label("2. Valeurs à comparer (facultatif — affichées sur la page de résultats)");
                egui::Grid::new("expected-values").num_columns(2).spacing([8.0, 6.0]).show(
                    ui,
                    |ui| {
                        ui.label("Empreinte de clôture attendue");
                        ui.add(
                            egui::TextEdit::singleline(&mut self.expected_closure_hash)
                                .hint_text("87694cf0…")
                                .desired_width(400.0),
                        );
                        ui.end_row();

                        ui.label("Graine d'ouverture");
                        ui.add(
                            egui::TextEdit::singleline(&mut self.expected_opening_seed)
                                .hint_text("uniquement en cas d'égalité, ex. a1b2c3…")
                                .desired_width(400.0),
                        );
                        ui.end_row();

                        ui.label("Vainqueur annoncé");
                        ui.add(
                            egui::TextEdit::singleline(&mut self.expected_winner)
                                .hint_text("identifiant de l'option, ex. option-b")
                                .desired_width(400.0),
                        );
                        ui.end_row();
                    },
                );
            });

            ui.add_space(8.0);

            let can_verify = self.csv_path.is_some();
            if ui
                .add_enabled(can_verify, egui::Button::new("Vérifier").min_size([120.0, 32.0].into()))
                .clicked()
            {
                self.run_verification();
            }

            ui.add_space(12.0);
            ui.separator();

            match &self.outcome {
                None => {}
                Some(Outcome::Error(err)) => {
                    ui.colored_label(egui::Color32::from_rgb(200, 40, 40), err);
                }
                Some(Outcome::Report(report)) => show_report(ui, report),
            }
        });
    }
}

fn show_report(ui: &mut egui::Ui, report: &Report) {
    egui::ScrollArea::vertical().show(ui, |ui| {
        ui.label(format!("Bulletins lus : {}", report.ballot_count));

        ui.horizontal(|ui| {
            ui.label("Empreinte de clôture recalculée :");
            ui.monospace(&report.closure_hash);
        });
        if let Some(agrees) = report.closure_hash_agrees {
            agreement_label(
                ui,
                agrees,
                "L'empreinte recalculée concorde avec celle attendue.",
                "L'empreinte recalculée NE concorde PAS avec celle attendue.",
            );
        }

        ui.add_space(6.0);
        ui.label(format!("Options : {}", report.options.join(", ")));

        ui.add_space(6.0);
        ui.label(
            "Matrice des duels (nombre de bulletins classant la ligne strictement devant la colonne) :",
        );
        egui::Grid::new("pairwise-matrix").striped(true).show(ui, |ui| {
            ui.label("");
            for option in &report.options {
                ui.monospace(option);
            }
            ui.end_row();
            for (i, row) in report.matrix.iter().enumerate() {
                ui.monospace(&report.options[i]);
                for value in row {
                    ui.label(value.to_string());
                }
                ui.end_row();
            }
        });

        ui.add_space(6.0);
        if report.schulze_winners.len() > 1 {
            ui.label(format!(
                "Égalité entre {} options selon la méthode Schulze : {}",
                report.schulze_winners.len(),
                report.schulze_winners.join(", ")
            ));
            match &report.tiebreak_order {
                Some(drawn) => {
                    ui.label(format!("Ordre de départage : {}", drawn.join(", ")));
                }
                None => {
                    ui.weak(
                        "Renseignez la graine d'ouverture ci-dessus pour rejouer le départage.",
                    );
                }
            }
        } else {
            ui.label(format!("Vainqueur Schulze : {}", report.schulze_winners.join(", ")));
        }

        if let Some(winner) = &report.final_winner {
            ui.add_space(4.0);
            ui.label(format!("Vainqueur retenu : {winner}"));
        }
        if let Some(agrees) = report.winner_agrees {
            agreement_label(
                ui,
                agrees,
                "Le vainqueur recalculé concorde avec celui annoncé.",
                "Le vainqueur recalculé NE concorde PAS avec celui annoncé.",
            );
        }
    });
}

fn agreement_label(ui: &mut egui::Ui, agrees: bool, when_true: &str, when_false: &str) {
    let (color, text) = if agrees {
        (egui::Color32::from_rgb(30, 140, 60), format!("✓ {when_true}"))
    } else {
        (egui::Color32::from_rgb(200, 40, 40), format!("✗ {when_false}"))
    };
    ui.colored_label(color, text);
}
